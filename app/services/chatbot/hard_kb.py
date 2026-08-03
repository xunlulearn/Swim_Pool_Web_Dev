"""Hard knowledge base: curated Q&A answered directly, without any LLM call.

Design contract
---------------
* Entries hold STATIC facts only. Anything whose answer depends on the
  current weather, time, or database rows must NOT live here — those keep
  going through the live pipeline. `_looks_like_live_query` enforces this
  even when a live question resembles a stored one.
* Matching is high precision by design: a wrong canned answer is far worse
  than a miss. A candidate must clear both a similarity threshold and a
  topic-anchor check before it can short-circuit the pipeline.
* Every entry is bilingual. The reply language follows the user's question.
* The same entries feed the clickable quick-question chips, so clicking a
  suggestion always lands on an exact match and answers instantly.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache
import random
import re
import unicodedata


# --------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------
# Each entry:
#   id       stable identifier
#   topic    anchor keywords; at least one must appear in the user question
#            (bilingual, matched loosely) before a fuzzy hit is accepted
#   zh/en    canonical question + answer per language
#   variants extra paraphrases used for matching only (never displayed)

HARD_KB_ENTRIES: list[dict] = [
    # ---------------- Weather & pool status rules (12) ----------------
    {
        "id": "lightning-cooldown",
        "topic": ("闪电", "雷电", "雷", "lightning", "thunder"),
        "zh": {
            "q": "受雷电影响关闭后，多久会重新开放？",
            "a": "闪电触发关闭后会进入 45 分钟冷却期，期间状态保持关闭，页面会显示预计重新开放的倒计时。如果冷却期内再次监测到 15 公里内的闪电，计时会重新开始。",
        },
        "en": {
            "q": "How long after a lightning closure does the pool reopen?",
            "a": "A lightning closure starts a 45-minute cooldown. The status stays CLOSED for the whole window and the page shows an estimated reopening countdown. If lightning within 15 km is detected again during the cooldown, the timer resets.",
        },
        "variants": (
            "闪电之后多久可以重新开放", "雷电关闭要等多久", "打雷后多久开放", "闪电冷却时间多长",
            "雷电后多长时间重新开放", "闪电关闭后多长时间会重新开放",
            "lightning cooldown duration", "how long is the lightning cooldown",
            "when does the pool reopen after lightning", "how long does lightning close the pool",
        ),
    },
    {
        "id": "lightning-threshold",
        "topic": ("闪电", "雷电", "lightning", "公里", "km", "距离", "distance"),
        "zh": {
            "q": "闪电在多少公里内泳池会关闭？",
            "a": "当监测到最近的闪电落点距离 NTU SRC 泳池 15 公里以内时，系统会判定为关闭（红色）。距离使用 Haversine 大圆距离公式计算，地球半径取 6371 公里。",
        },
        "en": {
            "q": "Within how many kilometres does lightning close the pool?",
            "a": "The pool is marked CLOSED (red) when the nearest detected strike is within 15 km of NTU SRC. Distance is computed with the Haversine great-circle formula using an Earth radius of 6,371 km.",
        },
        "variants": (
            "闪电多远会关闭泳池", "多少公里内的闪电会导致关闭", "闪电关闭的距离阈值是多少",
            "lightning distance threshold", "how close does lightning have to be to close the pool",
            "what is the lightning closure distance",
        ),
    },
    {
        "id": "rain-rule",
        "topic": ("雨", "降雨", "rain", "rainfall"),
        "zh": {
            "q": "大雨会怎么影响泳池状态？",
            "a": "当降雨量超过 5 毫米/小时时，系统判定为关闭，并进入 30 分钟冷却期，逻辑与闪电冷却相同：期间保持关闭并显示倒计时。",
        },
        "en": {
            "q": "How does heavy rain affect pool status?",
            "a": "Rainfall above 5 mm/h marks the pool CLOSED and starts a 30-minute cooldown, following the same logic as lightning: the status stays closed for the window with a countdown shown.",
        },
        "variants": (
            "下雨泳池会关闭吗", "降雨多大会关闭泳池", "雨天泳池状态怎么算", "大雨冷却多久",
            "heavy rain closure rule", "rainfall threshold for closing the pool",
            "does rain close the pool", "how long is the rain cooldown",
        ),
    },
    {
        "id": "status-colors",
        "topic": ("状态", "颜色", "绿色", "黄色", "红色", "status", "green", "amber", "red", "color"),
        "zh": {
            "q": "绿色、黄色、红色状态分别代表什么？",
            "a": "绿色（OPEN）表示条件正常，可以前往；黄色（WARNING）表示天气数据暂时不可用或需要留意，建议持续关注；红色（CLOSED）表示不应下水，已在池内的人应立即离水并听从救生员指示。",
        },
        "en": {
            "q": "What do the green, amber and red statuses mean?",
            "a": "GREEN (open) means conditions look fine to go. AMBER (warning) means weather data is temporarily unavailable or conditions need watching. RED (closed) means do not enter the water — anyone already swimming should leave and follow lifeguard instructions.",
        },
        "variants": (
            "黄色状态是什么意思", "红色状态代表什么", "amber 是什么意思", "状态颜色含义",
            "what does amber status mean", "what does red status mean",
            "meaning of the status colors", "what is the warning status",
        ),
    },
    {
        "id": "status-priority",
        "topic": ("状态", "判定", "优先", "逻辑", "status", "determine", "priority", "logic"),
        "zh": {
            "q": "系统是如何判定泳池开放或关闭的？",
            "a": "判定按优先级依次为：一，超出开放时段直接判为关闭；二，满足条件的社区共识可覆盖天气判断；三，天气数据不可用则为黄色警告；四，15 公里内有闪电则关闭并冷却 45 分钟；五，降雨超过 5 毫米/小时则关闭并冷却 30 分钟；以上都不满足即为开放。",
        },
        "en": {
            "q": "How does the system decide whether the pool is open or closed?",
            "a": "In priority order: outside operating hours is always closed; a qualifying community consensus overrides the weather verdict; unavailable weather data gives an amber warning; lightning within 15 km closes with a 45-minute cooldown; rainfall over 5 mm/h closes with a 30-minute cooldown; otherwise the pool shows as open.",
        },
        "variants": (
            "泳池状态怎么算出来的", "开放关闭的判断逻辑", "状态判定优先级是什么", "系统怎么决定开放还是关闭",
            "how is pool status determined", "what is the status decision logic",
            "status priority order",
        ),
    },
    {
        "id": "data-source",
        "topic": ("数据", "来源", "nea", "data", "source", "api"),
        "zh": {
            "q": "泳池状态的天气数据来自哪里？",
            "a": "来自新加坡国家环境局（NEA）的实时闪电与降雨公开接口，再结合用户的人工上报做交叉验证。页面底部注明数据有 1–3 分钟延迟，实际状态以现场救生员指示为准。",
        },
        "en": {
            "q": "Where does the weather data come from?",
            "a": "From Singapore NEA's real-time lightning and rainfall public APIs, cross-checked against crowdsourced user reports. The page notes a 1–3 minute data delay; the on-site lifeguard's instruction always takes precedence.",
        },
        "variants": (
            "数据是哪里来的", "天气数据来源是什么", "用的是什么天气接口", "nea 数据",
            "what is the data source", "which weather api do you use",
            "where does lightning data come from",
        ),
    },
    {
        "id": "refresh-rate",
        "topic": ("刷新", "更新", "多久", "频率", "refresh", "update", "often"),
        "zh": {
            "q": "泳池状态多久更新一次？",
            "a": "前端每 60 秒向后端拉取一次状态，后端对状态结果做 30 秒缓存以减少对 NEA 接口的压力。NEA 数据本身还有约 1–3 分钟的固有延迟。",
        },
        "en": {
            "q": "How often is the pool status updated?",
            "a": "The page polls the backend every 60 seconds, and the backend caches the status for 30 seconds to limit NEA API load. NEA's own data carries an inherent delay of roughly 1–3 minutes.",
        },
        "variants": (
            "多久刷新一次状态", "状态更新频率", "页面多久刷新", "数据多久更新",
            "how often does the status refresh", "status update frequency",
            "how frequently is data refreshed",
        ),
    },
    {
        "id": "nearest-lightning",
        "topic": ("最近", "闪电", "距离", "nearest", "lightning", "distance"),
        "zh": {
            "q": "首页的「最近闪电」是什么意思？",
            "a": "指最新一批 NEA 闪电数据中，距离 NTU SRC 泳池最近的一次落点的直线距离（公里）。当距离超过 15 公里时页面显示「>15km」表示安全；小于等于 15 公里则显示具体距离并触发关闭。",
        },
        "en": {
            "q": "What does 'Nearest Lightning' on the homepage mean?",
            "a": "It is the straight-line distance in km from the closest strike in the latest NEA snapshot to the NTU SRC pool. Above 15 km the page shows '>15km' (safe); at or below 15 km it shows the actual distance and triggers a closure.",
        },
        "variants": (
            "最近闪电怎么算", "nearest lightning 是什么", "最近闪电距离含义",
            "what is nearest lightning", "how is nearest lightning calculated",
        ),
    },
    {
        "id": "lightning-count",
        "topic": ("闪电", "数量", "count", "统计", "lightning"),
        "zh": {
            "q": "「闪电计数」统计的是什么范围？",
            "a": "统计最新一批 NEA 数据中，位于 NTU SRC 周围 30 公里范围内的闪电点数量，不是某个固定时间窗的累计值。状态卡与雷达图使用同一份快照，保证口径一致。",
        },
        "en": {
            "q": "What does the 'Lightning Count' cover?",
            "a": "It counts lightning points within 30 km of NTU SRC in the latest NEA snapshot — not a cumulative total over a fixed time window. The status card and the radar share the same snapshot so their figures always agree.",
        },
        "variants": (
            "闪电计数是什么意思", "闪电数量统计范围", "lightning count 时间窗",
            "what is lightning count", "what time window does lightning count use",
        ),
    },
    {
        "id": "rainfall-station",
        "topic": ("降雨", "站", "s44", "rainfall", "station"),
        "zh": {
            "q": "「降雨量 (S44)」中的 S44 是什么？",
            "a": "S44 是 NEA 的一个降雨监测站编号。系统会用 Haversine 距离从 NEA 返回的所有站点中自动挑选离 SRC 最近的一个，目前就是 S44。NEA 每 5 分钟更新一次（单位 mm/5min），系统换算为 mm/h 展示，该数据约有 10 分钟延迟。",
        },
        "en": {
            "q": "What is S44 in 'Rainfall (S44)'?",
            "a": "S44 is an NEA rainfall station ID. The system automatically picks the station nearest to SRC (by Haversine distance) from all stations NEA returns, which is currently S44. NEA updates every 5 minutes in mm/5min, converted to mm/h for display, with roughly a 10-minute delay.",
        },
        "variants": (
            "s44 是什么", "降雨站点怎么选的", "降雨数据来自哪个站",
            "what is the s44 station", "which rainfall station is used",
        ),
    },
    {
        "id": "trend-chart",
        "topic": ("趋势", "图表", "chart", "trend", "曲线"),
        "zh": {
            "q": "首页的闪电趋势图可以怎么看？",
            "a": "趋势图支持两个距离范围（15 公里、30 公里）和三个时间窗（20 分钟、1 小时、12 小时）。20 分钟和 1 小时按每个快照一根柱子展示，12 小时使用固定分箱覆盖完整 12 小时区间，与状态卡和雷达图同步刷新。",
        },
        "en": {
            "q": "How do I read the lightning trend chart?",
            "a": "The chart offers two distance filters (15 km and 30 km) and three time windows (20 minutes, 1 hour, 12 hours). The 20-minute and 1-hour views draw one bar per stored snapshot; the 12-hour view uses fixed bins spanning the full window. It refreshes in sync with the status card and radar.",
        },
        "variants": (
            "闪电趋势图怎么用", "趋势图有哪些筛选", "趋势图时间范围",
            "how does the trend chart work", "what filters does the lightning chart have",
        ),
    },
    {
        "id": "radar-map",
        "topic": ("雷达", "radar", "地图", "map"),
        "zh": {
            "q": "首页的雷达图显示的是什么？",
            "a": "雷达图以 NTU SRC 为圆心展示最新一批闪电落点，四圈刻度分别代表 7.5、15、22.5 和 30 公里。落点持续红色脉动，扫描线扫过时会短暂高亮，数据与状态卡使用同一份快照。",
        },
        "en": {
            "q": "What does the radar map on the homepage show?",
            "a": "It plots the latest lightning strikes centred on NTU SRC, with rings at 7.5, 15, 22.5 and 30 km. Points pulse red continuously and flash brighter as the sweep line passes them. The radar uses the same snapshot as the status card.",
        },
        "variants": (
            "雷达图怎么看", "雷达圈代表多少公里", "radar 显示什么",
            "what do the radar rings mean", "how to read the radar",
        ),
    },

    # ---------------- Operating hours (6) ----------------
    {
        "id": "hours-weekday",
        "topic": ("工作日", "平日", "周一", "周二", "周三", "周四", "周五", "weekday", "weekdays", "monday", "friday"),
        "zh": {
            "q": "工作日泳池的开放时间是几点到几点？",
            "a": "周一至周五的开放时间为早上 7:00 至晚上 21:30（新加坡时间）；作为对比，周末和公共假期为 8:00 至 20:00。在开放时段之外，状态卡一律显示关闭，与天气无关。",
        },
        "en": {
            "q": "What are the pool opening hours on weekdays?",
            "a": "Monday to Friday the pool is open from 07:00 to 21:30 Singapore time; for comparison, weekends and public holidays run 08:00 to 20:00. Outside the window the status card always shows closed, regardless of weather.",
        },
        "variants": (
            "工作日几点开门", "平时泳池几点开放", "周一到周五开放时间", "工作日泳池几点开放",
            "weekday opening hours", "what time does the pool open on weekdays",
            "when does the pool close on weekdays",
        ),
    },
    {
        "id": "hours-weekend",
        "topic": ("周末", "周六", "周日", "礼拜六", "礼拜天", "weekend", "saturday", "sunday"),
        "zh": {
            "q": "周末和公共假期的开放时间是什么？",
            "a": "周六、周日以及新加坡公共假期的开放时间为早上 8:00 至晚上 20:00（新加坡时间）；工作日则是 7:00 至 21:30，即周末比工作日晚开一小时、早关一个半小时。",
        },
        "en": {
            "q": "What are the opening hours on weekends and public holidays?",
            "a": "On Saturdays, Sundays and Singapore public holidays the pool is open from 08:00 to 20:00 Singapore time, while weekdays run 07:00 to 21:30 — so weekends open an hour later and close 90 minutes earlier.",
        },
        "variants": (
            "周末几点开门", "公共假期开放时间", "周六周日几点开放", "假期泳池几点开",
            "weekend opening hours", "public holiday opening hours",
            "what time does the pool open on sunday", "when does the pool close on weekends",
        ),
    },
    {
        "id": "hours-outside",
        "topic": ("非运营", "开放时段", "运营时间", "outside operating", "operating hours", "超出"),
        "zh": {
            "q": "为什么状态显示「超出开放时段」？",
            "a": "因为当前时间不在当天的开放时段内。此时无论天气如何，状态一律为关闭（红色），提示语中会写明当天适用的时段（工作日 07:00–21:30 或周末/假期 08:00–20:00）。开放后状态会自动恢复为按天气判断。",
        },
        "en": {
            "q": "Why does the status say 'Outside Operating Hours'?",
            "a": "Because the current time falls outside that day's opening window. The status is then CLOSED (red) regardless of weather, and the message states the schedule in effect (weekday 07:00–21:30 or weekend/holiday 08:00–20:00). Weather-based logic resumes once the pool reopens.",
        },
        "variants": (
            "为什么显示非运营时间", "超出开放时段是什么意思", "为什么会显示超出开放时段",
            "why does it say outside operating hours", "what does outside operating hours mean",
        ),
    },
    {
        "id": "holiday-schedule",
        "topic": ("假期", "假日", "holiday", "公共假期"),
        "zh": {
            "q": "公共假期用的是哪套开放时间？",
            "a": "新加坡公共假期套用周末时刻表，即 8:00 至 20:00。系统内置了 2026 与 2027 年的公共假期清单（含元旦、春节、开斋节、耶稣受难日、劳动节、哈芝节、卫塞节、国庆日、屠妖节、圣诞节及相应补假）。",
        },
        "en": {
            "q": "Which schedule applies on public holidays?",
            "a": "Singapore public holidays follow the weekend schedule, 08:00 to 20:00. The system ships the official 2026 and 2027 holiday lists, including New Year's Day, Chinese New Year, Hari Raya Puasa, Good Friday, Labour Day, Hari Raya Haji, Vesak Day, National Day, Deepavali, Christmas and their observed days.",
        },
        "variants": (
            "假期开放时间和周末一样吗", "公共假期泳池开放吗", "节假日时刻表",
            "are public holidays the same as weekends", "is the pool open on public holidays",
        ),
    },
    {
        "id": "hours-vacation",
        "topic": ("假期", "寒暑假", "vacation", "semester", "break"),
        "zh": {
            "q": "学校放假期间开放时间会变吗？",
            "a": "网站全年套用同一套工作日/周末/公共假期时刻表。如遇维护、活动或学期特殊安排导致临时调整，请以现场公告和救生员指示为准，它们的优先级高于网站显示。",
        },
        "en": {
            "q": "Do the opening hours change during university vacations?",
            "a": "The site applies the same weekday/weekend/holiday schedule all year round. For maintenance, events or special semester arrangements, follow the on-site notices and lifeguard instructions — they take precedence over the website.",
        },
        "variants": (
            "寒暑假开放时间一样吗", "放假期间开放时间", "学期休息时开放吗",
            "do hours change during holidays", "vacation opening hours",
        ),
    },
    {
        "id": "timezone",
        "topic": ("时间", "时区", "time", "timezone", "显示"),
        "zh": {
            "q": "网站上显示的时间是什么时区？",
            "a": "所有面向用户展示的时间都是新加坡时间（SGT，UTC+8），包括开放时段、上报时间戳和闪电观测时间。",
        },
        "en": {
            "q": "Which timezone do the times on the site use?",
            "a": "Every user-facing time is Singapore time (SGT, UTC+8) — operating hours, report timestamps and lightning observation times alike.",
        },
        "variants": (
            "时间是什么时区", "显示的是新加坡时间吗", "时区是什么",
            "what timezone is used", "are times in singapore time",
        ),
    },

    # ---------------- Manual reports (7) ----------------
    {
        "id": "report-how",
        "topic": ("上报", "报告", "report"),
        "zh": {
            "q": "我该如何提交手动泳池上报？",
            "a": "登录并完成邮箱验证后，在首页状态卡旁点击「Report Status」按钮，选择「泳池开放」或「泳池关闭」即可提交。游客可以查看上报，但不能提交。",
        },
        "en": {
            "q": "How can I submit a manual pool report?",
            "a": "Log in with a verified account, then use the 'Report Status' button next to the status card on the homepage and choose 'Pool is Open' or 'Pool is Closed'. Guests can view reports but cannot submit them.",
        },
        "variants": (
            "怎么上报泳池状态", "如何提交上报", "上报按钮在哪里", "怎么报告泳池开放",
            "how do i report pool status", "where is the report button",
            "how to submit a report",
        ),
    },
    {
        "id": "report-who",
        "topic": ("上报", "report", "谁", "who", "权限", "allowed"),
        "zh": {
            "q": "谁可以提交泳池上报？",
            "a": "只有已登录且完成邮箱验证的用户可以提交上报。这个限制是为了防止刷报，保证众包信号的可信度。",
        },
        "en": {
            "q": "Who is allowed to submit a pool report?",
            "a": "Only logged-in users whose email has been verified can submit reports. The restriction keeps the crowdsourced signal spam-free.",
        },
        "variants": (
            "谁能上报", "上报需要什么条件", "游客可以上报吗", "上报要登录吗",
            "who can submit reports", "can guests report", "do i need an account to report",
        ),
    },
    {
        "id": "report-consensus",
        "topic": ("上报", "共识", "覆盖", "report", "consensus", "override"),
        "zh": {
            "q": "需要多少条上报才能覆盖天气判定？",
            "a": "需要满足全部条件：30 分钟窗口内、来自 5 位不同真人用户的最近 5 条上报完全一致，且其中最新一条在 10 分钟以内。社区氛围账号（bot）的上报不计入共识。满足后共识会覆盖天气判定结果。",
        },
        "en": {
            "q": "How many reports are needed to override the weather status?",
            "a": "All of these must hold: the latest 5 reports within a 30-minute window come from 5 different human users and all agree, and the newest of them is under 10 minutes old. Community bot reports are excluded. When the consensus forms, it overrides the weather verdict.",
        },
        "variants": (
            "多少条上报能覆盖天气", "社区共识规则是什么", "几条上报可以改变状态", "共识条件是什么",
            "community consensus rule", "how does consensus override weather",
            "how many reports change the status",
        ),
    },
    {
        "id": "report-visibility",
        "topic": ("上报", "显示", "report", "visible", "列表", "feed"),
        "zh": {
            "q": "上报会在首页显示多久？",
            "a": "首页按提交时间倒序展示最新的 10 条上报，不按用户或状态去重；重复上报会作为独立记录逐条显示。超过 2 小时的会显示为灰色，以提示可能过时。",
        },
        "en": {
            "q": "How long do reports stay visible on the homepage?",
            "a": "The homepage shows the latest 10 report rows by submission time without deduplicating users or statuses, so repeated reports remain visible as separate records. Reports older than 2 hours are dimmed to flag that they may be stale.",
        },
        "variants": (
            "上报显示多久", "为什么有的上报是灰色的", "上报会保留多长时间", "首页显示几条上报",
            "how long are reports shown", "why are some reports greyed out",
            "how many reports are displayed",
        ),
    },
    {
        "id": "report-abuse",
        "topic": ("上报", "刷", "恶意", "report", "abuse", "fake"),
        "zh": {
            "q": "有人恶意乱上报怎么办？",
            "a": "共识规则要求 5 位不同真人用户在短时间内意见一致，单个人无法操纵状态。如果发现有账号持续恶意上报，可以通过首页底部的联系方式（微信或 Gmail）联系开发者处理。",
        },
        "en": {
            "q": "What if someone submits fake reports?",
            "a": "The consensus rule requires five different human users to agree within a short window, so no single person can manipulate the status. If an account keeps abusing reports, contact the developer through the WeChat or Gmail details in the page footer.",
        },
        "variants": (
            "有人乱报怎么办", "会不会有人刷上报", "恶意上报如何处理",
            "can someone game the reports", "what about fake reports",
        ),
    },
    {
        "id": "report-bot",
        "topic": ("机器人", "bot", "账号", "氛围", "account"),
        "zh": {
            "q": "社区里的机器人账号会影响泳池状态吗？",
            "a": "不会。氛围账号的上报被明确排除在社区共识计算之外，既不能形成共识，也不会破坏真人用户已形成的共识。它们只在泳池开放时段内活动。",
        },
        "en": {
            "q": "Do the community bot accounts affect the pool status?",
            "a": "No. Bot reports are explicitly excluded from the community consensus calculation — they can neither form a consensus nor break one formed by real users. They are also only active during pool operating hours.",
        },
        "variants": (
            "机器人上报算数吗", "bot 会影响状态吗", "氛围账号影响共识吗",
            "do bot reports count", "are bot accounts included in consensus",
        ),
    },
    {
        "id": "report-accuracy",
        "topic": ("准确", "可信", "accurate", "reliable", "trust", "状态"),
        "zh": {
            "q": "网站显示的状态准确吗？",
            "a": "系统结合 NEA 官方数据与用户众包上报做双重校验，但 NEA 数据本身有 1–3 分钟延迟（降雨约 10 分钟）。页面底部明确注明：实际状态以现场救生员的指示为准。",
        },
        "en": {
            "q": "How accurate is the status shown on the site?",
            "a": "The system cross-validates official NEA data with crowdsourced user reports, but NEA data carries a 1–3 minute delay (about 10 minutes for rainfall). As the page footer states, the on-site lifeguard's instruction is always the authority.",
        },
        "variants": (
            "状态准不准", "数据可靠吗", "显示的状态可信吗",
            "is the status reliable", "how accurate is the data",
        ),
    },

    # ---------------- Account & auth (9) ----------------
    {
        "id": "register",
        "topic": ("注册", "账号", "register", "account", "sign up"),
        "zh": {
            "q": "怎么注册账号？",
            "a": "打开注册页，填写用户名、邮箱和至少 8 位的密码，然后输入发送到邮箱的 6 位验证码完成验证。验证码 10 分钟内有效，60 秒后可以重新发送。请勿使用 NTU 校园邮箱注册。",
        },
        "en": {
            "q": "How do I register an account?",
            "a": "Open the Register page, provide a username, an email and a password of at least 8 characters, then enter the 6-digit code sent to your inbox. The code is valid for 10 minutes and can be resent after a 60-second cooldown. Do not use an NTU campus email.",
        },
        "variants": (
            "如何注册", "怎么创建账号", "注册流程是什么", "怎样开通账号",
            "how to sign up", "how do i create an account", "registration steps",
        ),
    },
    {
        "id": "ntu-email",
        "topic": ("ntu", "邮箱", "email", "验证码", "code"),
        "zh": {
            "q": "为什么不能用 NTU 邮箱注册？",
            "a": "NTU 校园邮箱（@ntu.edu.sg / @e.ntu.edu.sg）目前会拦截本站的验证邮件，导致收不到 6 位验证码。请改用 Gmail、Outlook 等个人邮箱注册；如果已用 NTU 邮箱注册且收不到码，直接用个人邮箱重新注册即可。",
        },
        "en": {
            "q": "Why can't I register with my NTU email?",
            "a": "NTU mailboxes (@ntu.edu.sg / @e.ntu.edu.sg) currently block the site's verification email, so the 6-digit code never arrives. Register with a personal mailbox such as Gmail or Outlook instead. If you already registered with an NTU address and cannot receive the code, simply register again with a personal email.",
        },
        "variants": (
            "ntu 邮箱收不到验证码", "为什么收不到验证码", "校园邮箱不能用吗", "用学校邮箱注册不了",
            "ntu email verification code not received", "why is my ntu email blocked",
            "can i use my school email",
        ),
    },
    {
        "id": "otp-not-received",
        "topic": ("验证码", "otp", "code", "收不到", "邮件"),
        "zh": {
            "q": "收不到验证码怎么办？",
            "a": "先检查垃圾邮件文件夹，并确认没有使用 NTU 校园邮箱。验证页面在 60 秒冷却后可以点击重新发送。注意连续输错 5 次会锁定 15 分钟。",
        },
        "en": {
            "q": "What should I do if the verification code never arrives?",
            "a": "Check your spam folder first and make sure you did not use an NTU campus email. You can resend the code from the verification page after a 60-second cooldown. Note that five wrong attempts lock the code for 15 minutes.",
        },
        "variants": (
            "验证码没收到", "验证邮件没来", "怎么重新发送验证码", "验证码过期了怎么办",
            "did not receive the code", "how do i resend the verification code",
            "verification email missing",
        ),
    },
    {
        "id": "otp-rules",
        "topic": ("验证码", "otp", "有效期", "code", "expire", "锁定"),
        "zh": {
            "q": "验证码的有效期和限制是什么？",
            "a": "验证码为 6 位数字，有效期 10 分钟。连续输错 5 次会锁定 15 分钟，重新发送验证码需间隔 60 秒。",
        },
        "en": {
            "q": "How long is the verification code valid?",
            "a": "The code is 6 digits and valid for 10 minutes. Five consecutive wrong attempts lock it for 15 minutes, and resending requires a 60-second gap.",
        },
        "variants": (
            "验证码多久过期", "验证码输错几次会锁", "重新发送要等多久",
            "verification code expiry", "how many attempts before lockout",
        ),
    },
    {
        "id": "reset-password",
        "topic": ("密码", "重置", "忘记", "password", "reset", "forgot"),
        "zh": {
            "q": "忘记密码了怎么重置？",
            "a": "在登录页点击「忘记密码」，输入注册邮箱，收取 6 位验证码后即可设置新密码。新密码至少 8 位。",
        },
        "en": {
            "q": "How do I reset a forgotten password?",
            "a": "Use 'Forgot password' on the login page, enter your registered email, receive the 6-digit code, then set a new password of at least 8 characters.",
        },
        "variants": (
            "怎么改密码", "密码忘了", "重置密码流程", "如何找回密码",
            "how to change my password", "i forgot my password", "password reset steps",
        ),
    },
    {
        "id": "password-rule",
        "topic": ("密码", "password", "要求", "长度", "requirement"),
        "zh": {
            "q": "密码有什么要求？",
            "a": "密码至少 8 个字符。建议使用足够复杂、且不与其他网站重复的密码。",
        },
        "en": {
            "q": "What are the password requirements?",
            "a": "The password must be at least 8 characters. A longer passphrase that you do not reuse on other sites is recommended.",
        },
        "variants": (
            "密码要多长", "密码规则是什么", "密码最少几位",
            "minimum password length", "password rules",
        ),
    },
    {
        "id": "profile-edit",
        "topic": ("昵称", "头像", "资料", "nickname", "avatar", "profile"),
        "zh": {
            "q": "怎么修改昵称和上传头像？",
            "a": "进入 Profile 页面的「编辑资料」，可以设置昵称并上传头像（JPEG 或 PNG，不超过 2MB）。昵称是别人在你的帖子、评论和上报旁看到的名字，用户名本身不可更改。",
        },
        "en": {
            "q": "How do I change my nickname or upload an avatar?",
            "a": "Open Profile → Edit profile to set a display nickname and upload an avatar (JPEG or PNG, up to 2 MB). The nickname is what others see next to your posts, comments and reports; the username itself stays fixed.",
        },
        "variants": (
            "怎么改昵称", "怎么换头像", "在哪里修改个人资料", "头像怎么上传",
            "how to change nickname", "how to upload avatar", "edit profile",
        ),
    },
    {
        "id": "guest-permissions",
        "topic": ("游客", "登录", "guest", "login", "权限", "without"),
        "zh": {
            "q": "不登录可以做什么？",
            "a": "游客可以查看泳池实时状态、闪电趋势图和雷达图、社区帖子列表以及帖子详情。提交上报、发帖、评论、点赞、收藏、私信和使用智能助手都需要登录并完成邮箱验证。",
        },
        "en": {
            "q": "What can I do without logging in?",
            "a": "Guests can view the live pool status, the lightning trend chart and radar, the community feed and individual posts. Submitting reports, posting, commenting, liking, saving, private messages and the assistant all require a verified logged-in account.",
        },
        "variants": (
            "游客能做什么", "不注册能看什么", "必须登录吗", "游客可以浏览社区吗",
            "what can guests do", "do i need to log in", "guest permissions",
        ),
    },
    {
        "id": "account-security",
        "topic": ("安全", "账号", "security", "account", "保护"),
        "zh": {
            "q": "账号安全方面网站做了什么？",
            "a": "密码经过哈希存储，登录与注册需邮箱 OTP 验证，所有会话使用 HttpOnly Cookie，所有写操作有 CSRF 保护，验证码错误 5 次锁定 15 分钟，智能助手也设有每分钟与每日的调用上限。",
        },
        "en": {
            "q": "What does the site do for account security?",
            "a": "Passwords are stored hashed, registration and login use email OTP verification, sessions use HttpOnly cookies, every write action is CSRF protected, five wrong codes lock the flow for 15 minutes, and the assistant enforces per-minute and per-day usage limits.",
        },
        "variants": (
            "账号安全吗", "网站怎么保护账号", "有没有安全措施",
            "is my account secure", "what security measures exist",
        ),
    },

    # ---------------- Community features (11) ----------------
    {
        "id": "search-posts",
        "topic": ("搜索", "search", "帖子", "post", "找"),
        "zh": {
            "q": "怎么在社区里搜索帖子？",
            "a": "社区页顶部有搜索框，支持按标题和正文关键词搜索，中英文都可以，并且可以与分类标签、翻页组合使用。已删除的帖子不会出现在结果中。",
        },
        "en": {
            "q": "How do I search for posts in the community?",
            "a": "Use the search box at the top of the Community page. It matches keywords in post titles and bodies in both English and Chinese, and combines with the category tabs and pagination. Deleted posts never appear in results.",
        },
        "variants": (
            "社区能搜索吗", "怎么找帖子", "搜索功能在哪里", "如何搜索帖子",
            "how to search posts", "where is the search box", "can i search the community",
        ),
    },
    {
        "id": "create-post",
        "topic": ("发帖", "发布", "post", "create", "写"),
        "zh": {
            "q": "怎么发布一个新帖子？",
            "a": "登录并完成邮箱验证后，在社区页点击「New Post」，选择分类、填写标题和正文，可选上传一张图片（JPEG 或 PNG，不超过 2MB）后发布。",
        },
        "en": {
            "q": "How do I create a new post?",
            "a": "Log in with a verified account, open the Community page and press 'New Post'. Choose a category, write a title and body, and optionally attach one image (JPEG or PNG, up to 2 MB).",
        },
        "variants": (
            "怎么发帖", "如何发布帖子", "发帖流程", "怎么写帖子",
            "how to post", "how do i publish a post", "creating a post",
        ),
    },
    {
        "id": "categories",
        "topic": ("分类", "category", "标签", "板块", "tab"),
        "zh": {
            "q": "社区有哪些分类？",
            "a": "社区分为四类：General（综合）、Find Buddy（约伴）、Lost & Found（失物招领）和 Tutorials（教程）。点击顶部标签即可筛选，筛选可以和搜索框、翻页一起使用。",
        },
        "en": {
            "q": "What categories does the community have?",
            "a": "Four categories: General, Find Buddy, Lost & Found and Tutorials. Select a tab at the top to filter the feed; the filter combines with the search box and pagination.",
        },
        "variants": (
            "有哪些板块", "怎么按分类筛选", "社区分类有什么", "帖子分类",
            "what are the post categories", "how to filter by category",
        ),
    },
    {
        "id": "comment-reply",
        "topic": ("评论", "回复", "comment", "reply"),
        "zh": {
            "q": "怎么评论和回复别人？",
            "a": "打开帖子详情页，在底部输入框填写内容即可评论；点击某条评论的回复按钮可以进行楼中楼回复。评论同样支持点赞，也可以附带图片。",
        },
        "en": {
            "q": "How do I comment and reply to others?",
            "a": "Open a post's detail page and use the input box at the bottom to comment. Use a comment's reply button for nested replies. Comments can be liked and can include an image.",
        },
        "variants": (
            "怎么评论", "如何回复评论", "楼中楼怎么用", "评论功能怎么用",
            "how to comment", "how do i reply to a comment", "nested replies",
        ),
    },
    {
        "id": "like-save",
        "topic": ("点赞", "收藏", "like", "save", "collect"),
        "zh": {
            "q": "怎么点赞和收藏帖子？",
            "a": "在帖子上点击点赞图标即可点赞（可再次点击取消），点击收藏可把帖子加入个人收藏。收藏过的帖子会显示在你的 Profile 个人主页，和你自己发过的帖子列在一起。",
        },
        "en": {
            "q": "How do I like and save posts?",
            "a": "Tap the like icon on a post to like it (tap again to undo), and use save/collect to bookmark it. Saved posts appear on your Profile page alongside the posts you have written.",
        },
        "variants": (
            "怎么点赞", "收藏在哪里看", "怎么收藏帖子", "我收藏的帖子在哪",
            "how to like a post", "where are my saved posts", "how to bookmark",
        ),
    },
    {
        "id": "delete-post",
        "topic": ("删除", "delete", "帖子", "post", "评论"),
        "zh": {
            "q": "怎么删除自己的帖子或评论？",
            "a": "打开自己的帖子或找到自己的评论，点击删除即可，只有作者本人和管理员可以删除。删除为软删除：内容从列表消失；如果被删的评论下面还有回复，会保留占位以免楼层断裂。",
        },
        "en": {
            "q": "How do I delete my own post or comment?",
            "a": "Open your post (or locate your comment) and use Delete — only the author and admins can do this. Deletion is a soft delete: the entry disappears from the feed, and a deleted comment that still has replies is kept as a placeholder so the thread stays readable.",
        },
        "variants": (
            "怎么删帖", "能删除评论吗", "删除的帖子还能恢复吗",
            "how to delete a post", "can i delete my comment",
        ),
    },
    {
        "id": "report-content",
        "topic": ("举报", "report", "不当", "违规", "inappropriate"),
        "zh": {
            "q": "怎么举报不当内容？",
            "a": "每个帖子和评论都有举报入口，填写举报原因即可提交。同一内容每人只能举报一次，也不能举报自己发的内容。管理员会在后台审核处理。",
        },
        "en": {
            "q": "How do I report inappropriate content?",
            "a": "Every post and comment has a Report option where you give a reason. Each user can report a given item once and cannot report their own content. Admins review submissions in a dedicated dashboard.",
        },
        "variants": (
            "怎么举报帖子", "举报评论怎么操作", "看到违规内容怎么办",
            "how to report a post", "reporting inappropriate content",
        ),
    },
    {
        "id": "private-message",
        "topic": ("私信", "message", "聊天", "chat", "dm"),
        "zh": {
            "q": "怎么给其他用户发私信？",
            "a": "已验证用户可以进入对方的个人主页，或通过消息页发起一对一私信。导航栏会显示未读消息数量。",
        },
        "en": {
            "q": "How do I send a private message to another user?",
            "a": "Verified users can open another user's profile or use the Messages page to start a one-to-one conversation. Unread counts appear in the navigation bar.",
        },
        "variants": (
            "怎么私聊", "私信功能在哪", "怎么发消息给别人",
            "how to send a dm", "where are private messages",
        ),
    },
    {
        "id": "post-image",
        "topic": ("图片", "image", "上传", "upload", "照片", "photo"),
        "zh": {
            "q": "发帖可以上传图片吗？有什么限制？",
            "a": "可以。每个帖子或评论支持一张图片，格式限 JPEG 或 PNG，大小不超过 2MB。编辑帖子时也可以替换或移除已上传的图片。",
        },
        "en": {
            "q": "Can I attach images to posts, and what are the limits?",
            "a": "Yes. A post or comment can carry one image in JPEG or PNG format, up to 2 MB. When editing a post you can replace or remove the existing image.",
        },
        "variants": (
            "帖子能发图片吗", "图片大小限制", "支持什么图片格式",
            "can i upload photos", "image size limit", "supported image formats",
        ),
    },
    {
        "id": "find-buddy",
        "topic": ("约伴", "搭子", "buddy", "squad", "一起"),
        "zh": {
            "q": "想找人一起游泳该发在哪里？",
            "a": "发在 Find Buddy（约伴）分类下。建议在帖子里写清楚大致时间段和期望配速，方便别人判断是否合适；也可以先用搜索框看看有没有时间接近的现成帖子。",
        },
        "en": {
            "q": "Where should I post if I want to find a swim buddy?",
            "a": "Use the Find Buddy category. Mentioning a rough time slot and your expected pace helps others decide quickly. You can also search first to see whether someone already posted a matching time.",
        },
        "variants": (
            "怎么找游泳搭子", "约伴发在哪个分类", "想找人一起游泳",
            "how to find a swim buddy", "which category for meetups",
        ),
    },
    {
        "id": "lost-found",
        "topic": ("失物", "丢", "lost", "found", "捡到"),
        "zh": {
            "q": "东西丢在泳池了怎么办？",
            "a": "可以在 Lost & Found（失物招领）分类发帖，写清楚物品特征和大致丢失时间。也建议先到 SRC 前台询问，捡到东西的人通常会交到那里。",
        },
        "en": {
            "q": "What should I do if I lost something at the pool?",
            "a": "Post in the Lost & Found category with a clear description of the item and roughly when you lost it. It is also worth asking at the SRC counter first, since found items are usually handed in there.",
        },
        "variants": (
            "丢东西了怎么办", "失物招领在哪", "泳镜丢了怎么找",
            "i lost my goggles", "lost and found",
        ),
    },

    # ---------------- Assistant & site info (5) ----------------
    {
        "id": "assistant-scope",
        "topic": ("助手", "assistant", "chatbot", "机器人", "能做"),
        "zh": {
            "q": "这个智能助手能回答哪些问题？",
            "a": "可以回答泳池实时状态、现在适不适合游泳、闪电与降雨规则、开放时间、手动上报、社区帖子查询以及网站使用方法等问题。需要登录后使用，会用你提问的语言回复。",
        },
        "en": {
            "q": "What questions can this assistant answer?",
            "a": "Live pool status, whether it makes sense to swim now, lightning and rainfall rules, opening hours, manual reports, community post lookups and how to use the site. It requires login and replies in the language you use.",
        },
        "variants": (
            "助手能做什么", "chatbot 能回答什么", "你能帮我什么",
            "what can the assistant do", "what can i ask you",
        ),
    },
    {
        "id": "assistant-limit",
        "topic": ("限制", "次数", "limit", "rate", "上限"),
        "zh": {
            "q": "智能助手有使用次数限制吗？",
            "a": "有。为控制成本设有公平使用上限：每分钟最多 8 条消息，每天最多 80 条。超出时会提示稍后再试。",
        },
        "en": {
            "q": "Is there a usage limit on the assistant?",
            "a": "Yes. Fair-use limits keep costs in check: up to 8 messages per minute and 80 per day. Exceeding either shows a message asking you to try again shortly.",
        },
        "variants": (
            "助手能问多少次", "有使用上限吗", "每天能问几次",
            "how many messages can i send", "assistant rate limit",
        ),
    },
    {
        "id": "site-purpose",
        "topic": ("网站", "site", "ntupool", "项目", "about", "做什么"),
        "zh": {
            "q": "这个网站是做什么的？",
            "a": "NTU Pool（ntupool.org）帮助 NTU 师生了解泳池是否因天气或时段而关闭，减少白跑一趟的情况，同时提供一个游泳爱好者的社区，用于约伴、交流技巧和失物招领。",
        },
        "en": {
            "q": "What is this website for?",
            "a": "NTU Pool (ntupool.org) helps NTU students and staff tell whether the pool is closed due to weather or operating hours, so nobody walks over for nothing. It also hosts a swimming community for finding buddies, sharing tips and lost-and-found.",
        },
        "variants": (
            "这个网站干什么的", "ntupool 是什么", "网站介绍",
            "what is ntupool", "about this site",
        ),
    },
    {
        "id": "tech-stack",
        "topic": ("技术", "tech", "开发", "stack", "怎么做的", "开源"),
        "zh": {
            "q": "这个网站是用什么技术做的？",
            "a": "后端使用 Python Flask，数据库为 PostgreSQL，部署在 Vercel，天气数据来自新加坡 NEA 公开接口，智能助手基于向量检索加大语言模型。项目开源，仓库地址见页面底部。",
        },
        "en": {
            "q": "What technology is this site built with?",
            "a": "A Python Flask backend with PostgreSQL, deployed on Vercel, using Singapore NEA's public weather APIs, and an assistant built on vector retrieval plus a large language model. The project is open source; the repository link is in the page footer.",
        },
        "variants": (
            "用什么技术栈", "网站怎么开发的", "是开源的吗",
            "what tech stack", "is this open source", "how was this built",
        ),
    },
    {
        "id": "contact",
        "topic": ("联系", "contact", "反馈", "feedback", "开发者", "developer"),
        "zh": {
            "q": "怎么联系网站开发者或反馈问题？",
            "a": "每个页面底部都有开源 GitHub 仓库链接和联系方式（微信、Gmail）。功能建议、问题反馈和错误报告都欢迎通过这些渠道提出。",
        },
        "en": {
            "q": "How do I contact the developer or send feedback?",
            "a": "Every page footer lists the open-source GitHub repository and contact channels (WeChat and Gmail). Feature suggestions, questions and bug reports are all welcome there.",
        },
        "variants": (
            "怎么联系开发者", "在哪里反馈问题", "有问题找谁", "联系方式是什么",
            "how to contact the developer", "where do i give feedback", "report a bug",
        ),
    },
]


# --------------------------------------------------------------------------
# Live-question guard
# --------------------------------------------------------------------------
# Questions asking about the CURRENT situation must never be answered from a
# static entry, even when they look similar to a stored one.
LIVE_QUERY_MARKERS = (
    "现在", "此刻", "当前", "今天", "刚才", "这会儿", "马上", "待会",
    "right now", "at the moment", "currently", "today", "just now", "tonight",
)
LIVE_QUERY_SUBJECTS = (
    "开放", "关闭", "开门", "关门", "状态", "能去", "可以去", "适合", "人多",
    "open", "closed", "status", "go swimming", "swim", "busy", "crowded", "safe",
)

# Questions scoping CONCRETE STORED RECORDS ("今天有多少条上报") are database
# lookups, not static rules, even though they share vocabulary with rule
# entries ("需要几条上报才能覆盖天气").
DATA_QUERY_MARKERS = (
    "今天", "昨天", "最近", "最新", "列出", "有哪些", "本周", "这周", "本月",
    "latest", "newest", "recent", "today", "yesterday", "list ", "show me",
)
DATA_QUERY_ENTITIES = (
    "上报", "帖子", "评论", "report", "reports", "post", "posts", "comment", "comments",
)


def _looks_like_live_query(normalized_question: str, raw_question: str) -> bool:
    """True when the question is about the current situation or stored rows."""
    lowered = (raw_question or "").lower()
    if any(marker in lowered for marker in LIVE_QUERY_MARKERS) and any(
        subject in lowered for subject in LIVE_QUERY_SUBJECTS
    ):
        return True
    return any(marker in lowered for marker in DATA_QUERY_MARKERS) and any(
        entity in lowered for entity in DATA_QUERY_ENTITIES
    )


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------
_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)
_CJK_RE = re.compile(r"[一-鿿]")

EN_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did", "to",
    "of", "for", "on", "in", "at", "by", "from", "with", "and", "or", "i",
    "you", "we", "it", "this", "that", "my", "me", "can", "could", "would",
    "should", "will", "be", "have", "has", "get", "there", "what", "how",
    "when", "where", "why", "who", "which", "if", "about", "please", "tell",
}

# A question that shares a topic anchor with an entry only needs a moderate
# similarity: the anchor already constrains the subject. Without an anchor,
# only a near-verbatim match is accepted.
ANCHORED_THRESHOLD = 0.42
UNANCHORED_THRESHOLD = 0.86
# When two DIFFERENT entries score within this margin the question is
# ambiguous (e.g. several lightning entries) — fall through to the live
# pipeline rather than guess a canned answer.
AMBIGUITY_MARGIN = 0.05


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", (text or "")).strip().lower()
    return _PUNCT_RE.sub("", value)


def _tokens(text: str) -> set[str]:
    """Word tokens for English, character bigrams for CJK."""
    value = unicodedata.normalize("NFKC", (text or "")).strip().lower()
    words = {
        token for token in re.findall(r"[a-z0-9]+", value)
        if token and token not in EN_STOPWORDS
    }
    cjk = "".join(_CJK_RE.findall(value))
    bigrams = {cjk[i:i + 2] for i in range(len(cjk) - 1)} if len(cjk) >= 2 else set()
    if len(cjk) == 1:
        bigrams = {cjk}
    return words | bigrams


def _similarity(query: str, candidate: str) -> float:
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(candidate)
    if not query_tokens or not candidate_tokens:
        return 0.0
    overlap = len(query_tokens & candidate_tokens)
    # Coverage of the shorter side rewards a query that is a subset of the
    # canonical phrasing ("闪电冷却多久" vs the full canonical question).
    coverage = overlap / min(len(query_tokens), len(candidate_tokens))
    jaccard = overlap / len(query_tokens | candidate_tokens)
    sequence = SequenceMatcher(None, _normalize(query), _normalize(candidate)).ratio()
    return max(0.62 * coverage + 0.38 * jaccard, sequence * 0.94)


@lru_cache(maxsize=1)
def _match_index() -> tuple[tuple[str, str], ...]:
    """(entry_id, candidate_text) pairs for every phrasing we accept."""
    pairs: list[tuple[str, str]] = []
    for entry in HARD_KB_ENTRIES:
        for lang in ("zh", "en"):
            pairs.append((entry["id"], entry[lang]["q"]))
        for variant in entry.get("variants", ()):
            pairs.append((entry["id"], variant))
    return tuple(pairs)


@lru_cache(maxsize=1)
def _entry_by_id() -> dict[str, dict]:
    return {entry["id"]: entry for entry in HARD_KB_ENTRIES}


@lru_cache(maxsize=1)
def _exact_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for entry_id, text in _match_index():
        index.setdefault(_normalize(text), entry_id)
    return index


@lru_cache(maxsize=2048)
def _anchor_pattern(anchor: str):
    """Word-boundary matcher for ASCII anchors; substring for CJK.

    Without boundaries, the anchor "api" would fire inside "c-api-tal" and
    hand an unrelated question a canned answer.
    """
    escaped = re.escape(anchor)
    prefix = r"\b" if anchor[:1].isalnum() else ""
    # Common English inflections so "save" anchors "saved", "open" anchors
    # "opening". The leading \b still prevents fragment matches ("api" can
    # never fire inside "capital").
    suffix = r"(?:s|es|d|ed|ing)?\b" if anchor[-1:].isalpha() else (
        r"\b" if anchor[-1:].isalnum() else ""
    )
    return re.compile(prefix + escaped + suffix)


def _has_topic_anchor(question: str, entry: dict) -> bool:
    lowered = (question or "").lower()
    for topic in entry.get("topic", ()):
        anchor = str(topic).lower()
        if not anchor:
            continue
        if _CJK_RE.search(anchor):
            if anchor in lowered:
                return True
        elif _anchor_pattern(anchor).search(lowered):
            return True
    return False


def match_hard_kb(question: str):
    """Return (entry, score) for a confident match, else None.

    Precision-first, in this order:
      1. Live/current-situation questions never match a static entry.
      2. An exact normalized match wins immediately.
      3. A fuzzy candidate sharing a topic anchor needs only a moderate
         score; without an anchor it must be near-verbatim.
      4. If two different entries are within AMBIGUITY_MARGIN the question
         is treated as ambiguous and falls through to the live pipeline.
    """
    text = (question or "").strip()
    if not text:
        return None

    normalized = _normalize(text)
    if not normalized:
        return None
    if _looks_like_live_query(normalized, text):
        return None

    exact_id = _exact_index().get(normalized)
    if exact_id:
        return _entry_by_id()[exact_id], 1.0

    # Best score per entry.
    per_entry: dict[str, float] = {}
    for entry_id, candidate in _match_index():
        score = _similarity(text, candidate)
        if score > per_entry.get(entry_id, 0.0):
            per_entry[entry_id] = score
    if not per_entry:
        return None

    # Topic anchors participate in RANKING, not just in a threshold check:
    # an on-topic entry is a far better candidate than a higher-scoring
    # entry about something else entirely.
    anchored = [
        (entry_id, score)
        for entry_id, score in per_entry.items()
        if _has_topic_anchor(text, _entry_by_id()[entry_id])
    ]
    if anchored:
        best_id, best_score = max(anchored, key=lambda item: item[1])
        if best_score < ANCHORED_THRESHOLD:
            return None
        return _entry_by_id()[best_id], best_score

    best_id, best_score = max(per_entry.items(), key=lambda item: item[1])
    if best_score < UNANCHORED_THRESHOLD:
        return None
    return _entry_by_id()[best_id], best_score


def answer_for(entry: dict, language: str) -> str:
    lang = "zh" if language == "zh" else "en"
    return entry[lang]["a"]


def question_for(entry: dict, language: str) -> str:
    lang = "zh" if language == "zh" else "en"
    return entry[lang]["q"]


def suggested_questions(language: str, *, count: int = 3, exclude_ids=()) -> list[str]:
    """Random canonical questions for the clickable suggestion chips.

    Clicking one sends its exact canonical text, which then matches the hard
    KB exactly and is answered instantly with no model call.
    """
    excluded = set(exclude_ids or ())
    pool = [entry for entry in HARD_KB_ENTRIES if entry["id"] not in excluded]
    if not pool:
        pool = list(HARD_KB_ENTRIES)
    picks = random.sample(pool, k=min(max(1, count), len(pool)))
    return [question_for(entry, language) for entry in picks]


def hard_kb_size() -> int:
    return len(HARD_KB_ENTRIES)
