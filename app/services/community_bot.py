"""Community bot scheduler.

Design goals (in order of importance):

1. Never act outside pool operating hours. All bot activity (posts, pool
   reports, comments, likes) happens inside the SGT operating window,
   shrunk by an edge buffer so bots do not act suspiciously at the exact
   opening/closing minute.
2. Spread activity randomly across the whole day. Each 30-minute cron tick
   rolls an independent probability of ``remaining_actions / remaining_ticks``
   per action type, which yields an approximately uniform distribution over
   the remaining window while still guaranteeing the daily target is met.
3. Look human. Templates are grouped by time-of-day bucket (morning /
   midday / evening) so "tonight" never shows up in a 9 AM post, recently
   used titles are not repeated, timestamps are scattered off the tick
   boundary, and pool reports are decoupled from posts (different bot,
   different minute).
4. Interact, not just broadcast. Bots comment on and like recent posts,
   prioritising human posts that received no replies.
"""

import random
from datetime import datetime, timedelta

from app.extensions import db
from app.models.bot import BotAccount, BotActivityLog, BotDailyPostPlan
from app.models.content import Comment, Post
from app.models.interaction import Like
from app.models.report import PoolReport
from app.models.user import User
from app.services import operating_hours
from app.services.weather_engine import weather_engine


SGT_OFFSET = timedelta(hours=8)

TICK_INTERVAL_MINUTES = 30
# Bots never act within 30 minutes of opening/closing time.
ACTION_WINDOW_EDGE_BUFFER = timedelta(minutes=30)
# Scatter created_at a little before the tick time so activity does not
# align on :00/:30 boundaries.
MAX_TIMESTAMP_SCATTER_MINUTES = 17

DAILY_MIN_POSTS = 2
DAILY_MAX_POSTS = 6
DAILY_MIN_REPORTS = 3
DAILY_MAX_REPORTS = 7
DAILY_MIN_COMMENTS = 2
DAILY_MAX_COMMENTS = 5
DAILY_MIN_LIKES = 4
DAILY_MAX_LIKES = 10

ACTION_CREATE_POST = 'create_post'
ACTION_POOL_REPORT = 'pool_report'
ACTION_CREATE_COMMENT = 'create_comment'
ACTION_LIKE_POST = 'like_post'
ACTION_DEDUPE_CLEANUP = 'dedupe_cleanup'

# Do not repeat a post title that any bot used within this window.
TEMPLATE_REUSE_LOOKBACK_DAYS = 10
# Interaction targets: how far back bots look for posts to engage with.
HUMAN_POST_LOOKBACK = timedelta(days=7)
BOT_POST_LOOKBACK = timedelta(hours=72)
MAX_BOT_COMMENTS_PER_POST = 2
MAX_TOTAL_COMMENTS_FOR_TARGET = 3

BOT_AVATAR_COLORS = (
    'f6bd60',
    'f28482',
    '84a59d',
    '90dbf4',
    'a3c4f3',
    'cfbaf0',
    'ffcfd2',
    'b9fbc0',
    'fde68a',
    'fca5a5',
)
BOT_AVATAR_SOURCES = (
    ('dicebear', 'pixel-art'),
    ('loremflickr', 'landscape'),
    ('dicebear', 'shapes'),
    ('loremflickr', 'cat'),
    ('dicebear', 'thumbs'),
    ('picsum', 'photo'),
    ('dicebear', 'icons'),
    ('loremflickr', 'dog'),
    ('dicebear', 'glass'),
    ('loremflickr', 'ocean'),
    ('dicebear', 'identicon'),
    ('loremflickr', 'bird'),
    ('dicebear', 'pixel-art-neutral'),
    ('loremflickr', 'mountain'),
    ('dicebear', 'rings'),
    ('loremflickr', 'flower'),
    ('dicebear', 'shape-grid'),
    ('loremflickr', 'forest'),
    ('dicebear', 'glass'),
    ('loremflickr', 'waterfall'),
    ('picsum', 'photo'),
    ('loremflickr', 'sky'),
    ('dicebear', 'triangles'),
    ('loremflickr', 'garden'),
    ('dicebear', 'thumbs'),
    ('loremflickr', 'animal'),
)


BOT_PERSONAS = [
    ('avery_laps', '小瓶盖', 'squad', '晚课后约轻松游的中文校园搭子'),
    ('ben_easy_pace', '抹茶布丁', 'squad', '适合新手游泳的中文约伴号'),
    ('chloe_kickboard', '年少寻梦', 'tutorial', '耐心记录训练小技巧的中文身份'),
    ('daniel_src', '森予清风', 'general', '常问泳池实用信息的中文同学'),
    ('emily_splits', '云端打卡', 'tutorial', '喜欢记录配速和小目标的中文身份'),
    ('farah_swims', '月亮邮递员', 'squad', '温和组织结伴游泳的中文同学'),
    ('gabriel_lane4', '小胜同学', 'general', '课间关注泳池人流的中文身份'),
    ('hannah_pullbuoy', '风吹少女心', 'tutorial', '分享轻量练习提醒的中文身份'),
    ('isaac_afterclass', '半袖桃花', 'squad', '下课后找游泳搭子的中文同学'),
    ('jasmine_poolbag', '持伞猫', 'lostfound', '帮忙提醒失物招领的中文身份'),
    ('kai_warmup', '晨风暖', 'tutorial', '喜欢热身和恢复建议的中文身份'),
    ('leah_morning', '山有木兮', 'squad', '早场游泳常客的中文同学'),
    ('marcus_ntu', '南方有梦', 'general', '关心泳道拥挤度的中文身份'),
    ('nina_freestyle', '一夜听春雨', 'tutorial', '学习自由泳技巧的中文身份'),
    ('owen_sprints', '元气小坏坏', 'squad', '喜欢短组训练的中文同学'),
    ('priya_lanes', '远山迷雾', 'general', '友好询问泳池状态的中文身份'),
    ('quentin_pool', '青藤之凉', 'lostfound', '发布失物提醒的中文身份'),
    ('rachel_easy', '浅色夏沫', 'squad', '组织轻松配速的中文同学'),
    ('sam_strokes', '橘子海盐', 'tutorial', '分享基础泳姿心得的中文身份'),
    ('tessa_src', '课后去游泳', 'general', '会看天气再去泳池的中文同学'),
    ('umar_laps', 'Umar Aziz', 'squad', 'steady lap partner'),
    ('vivian_swim', 'Vivian Foo', 'tutorial', 'beginner tip collector'),
    ('wayne_goggles', 'Wayne Neo', 'lostfound', 'gear and locker reminder'),
    ('xin_evening', 'Xin Zhou', 'squad', 'evening swim planner'),
    ('yara_breathing', 'Yara Lee', 'tutorial', 'breathing drill fan'),
    ('zach_lane', 'Zachary Tan', 'general', 'lane availability asker'),
    ('amelia_src', 'Amelia Wee', 'squad', 'weekend swim buddy'),
    ('brandon_sets', 'Brandon Chua', 'tutorial', 'set-building note sharer'),
    ('celine_pool', 'Celine Ang', 'general', 'asks low-pressure questions'),
    ('darren_kicks', 'Darren Sim', 'tutorial', 'kick drill person'),
    ('ella_sunday', 'Ella Ho', 'squad', 'weekend meetup organizer'),
    ('finn_lapwatch', 'Finn Tan', 'general', 'pool timing observer'),
    ('grace_backstroke', 'Grace Lau', 'tutorial', 'backstroke beginner'),
    ('haris_swim', 'Haris Ismail', 'squad', 'steady beginner pace'),
    ('iris_lostfound', 'Iris Koh', 'lostfound', 'lost item thread starter'),
    ('jon_poolchat', 'Jon Lim', 'general', 'conversation starter'),
    ('kelly_form', 'Kelly Ng', 'tutorial', 'form checklist sharer'),
    ('liam_noon', 'Liam Wee', 'squad', 'lunchtime swimmer'),
    ('mei_lanes', 'Mei Zhang', 'general', 'lane crowd checker'),
    ('noah_pull', 'Noah Goh', 'tutorial', 'pull set fan'),
    ('olivia_easy', 'Olivia Tan', 'squad', 'easy swim planner'),
    ('peter_weather', 'Peter Chua', 'general', 'weather-conscious swimmer'),
    ('qian_src', 'Qian Lee', 'squad', 'quiet swim buddy'),
    ('reina_drills', 'Reina Ong', 'tutorial', 'drill collector'),
    ('sean_kickset', 'Sean Low', 'tutorial', 'kick-set regular'),
    ('tricia_bag', 'Tricia Foo', 'lostfound', 'gear reminder poster'),
    ('vincent_lanes', 'Vincent Tay', 'general', 'crowd-level asker'),
    ('wendy_swims', 'Wendy Chan', 'squad', 'after-dinner swim organizer'),
    ('xavier_tempo', 'Xavier Yeo', 'tutorial', 'tempo and pacing voice'),
    ('zoe_src', 'Zoe Tan', 'general', 'friendly check-in poster'),
]


CHINESE_PERSONA_KEYS = frozenset(persona[0] for persona in BOT_PERSONAS[:20])

BUCKET_MORNING = 'morning'
BUCKET_MIDDAY = 'midday'
BUCKET_EVENING = 'evening'
BUCKET_ANY = 'any'

# Post templates, grouped by archetype -> time bucket -> [(title, body), ...].
# 'any' templates are safe at any hour; bucket templates may reference the
# time of day and are only used inside that bucket.
POST_TEMPLATES = {
    'general': {
        BUCKET_ANY: [
            (
                'How busy has SRC pool been lately?',
                'I am trying to figure out the calmer windows this week. Has anyone noticed whether late afternoon or after dinner feels less crowded?'
            ),
            (
                'Best time for a relaxed swim?',
                'For people who prefer easy laps without rushing, which time slot has felt the most comfortable recently?'
            ),
            (
                'How many lanes are usually open?',
                'Just wondering how many lap lanes are normally available at SRC, and whether they close some lanes for classes or events.'
            ),
            (
                'Do you check the status card before going?',
                'The homepage status card with lightning distance has been handy. Curious how everyone else decides whether to head over.'
            ),
        ],
        BUCKET_MORNING: [
            (
                'Morning lap lanes filling up early?',
                'Thinking of a short swim before my first class. Does the pool get busy right after opening, or is the first hour usually calm?'
            ),
            (
                'Quiet swim before noon?',
                'I am free until midday and hoping for a relaxed session. Anyone around the pool who can share how it looks this morning?'
            ),
        ],
        BUCKET_MIDDAY: [
            (
                'Lunchtime swim, worth it?',
                'Trying to squeeze in laps between classes. Is the early afternoon usually calm, or does it get busy after lunch?'
            ),
            (
                'How is the pool this afternoon?',
                'Weather looks decent from where I am. If anyone passes by SRC this afternoon, a quick crowd update would help.'
            ),
        ],
        BUCKET_EVENING: [
            (
                'Quick pool check for tonight',
                'Planning a short swim later tonight if the weather stays reasonable. If anyone passes by SRC, a quick crowd update would be helpful.'
            ),
            (
                'Post-dinner swim crowd?',
                'Does the pool stay busy after dinner time, or does it quiet down closer to closing? Trying to pick a relaxed slot tonight.'
            ),
        ],
    },
    'squad': {
        BUCKET_ANY: [
            (
                'Looking for beginner-friendly lane buddies',
                'Would anyone be interested in a casual swim group where stopping between sets is totally fine?'
            ),
            (
                'Weekend swim buddy?',
                'Looking for someone to do easy laps with on weekends. No pace pressure, just showing up consistently.'
            ),
        ],
        BUCKET_MORNING: [
            (
                'Early laps together this morning?',
                'Doing an easy 30 minutes this morning before things get busy. Anyone up for a no-pressure session?'
            ),
        ],
        BUCKET_MIDDAY: [
            (
                'Lunch break swim anyone?',
                'Planning a quick session around lunch. Happy to share a lane and keep it relaxed if anyone is free.'
            ),
        ],
        BUCKET_EVENING: [
            (
                'Easy pace swim later tonight?',
                'I am thinking of doing 30-40 minutes at a relaxed pace this evening. Anyone else aiming for a simple no-pressure session?'
            ),
            (
                'Short evening set idea',
                'Maybe 200 warmup, a few relaxed 50s, then easy cooldown. Happy to join if someone is planning something similar tonight.'
            ),
        ],
    },
    'tutorial': {
        BUCKET_ANY: [
            (
                'Small freestyle cue that helped me',
                'Thinking about exhaling steadily underwater made breathing feel less rushed. Curious if others have simple cues that worked for them.'
            ),
            (
                'Kick drill reminder',
                'A few slow kickboard lengths can be useful before harder sets. I try to keep the kick small instead of splashing too much.'
            ),
            (
                'Easy warmup structure',
                'For short swims, I like starting with 4 gentle lengths before doing anything faster. It makes the rest of the session feel smoother.'
            ),
            (
                'Pacing on longer swims',
                'I keep starting too fast and fading halfway. Counting strokes per length helped me hold an even pace. What works for you?'
            ),
            (
                'Shoulder care after swimming',
                'Gentle band work and not overreaching on the catch helped my shoulders a lot. Sharing in case anyone else gets the same soreness.'
            ),
        ],
    },
    'lostfound': {
        BUCKET_ANY: [
            (
                'Lost-and-found check',
                'If anyone spots goggles, caps, or towels left near the pool area today, maybe drop a note here so the owner has a better chance of finding them.'
            ),
            (
                'Pool bag reminder',
                'Tiny reminder to check the bench and shower area before leaving. Goggles and caps seem very easy to forget after a swim.'
            ),
            (
                'Where do lost items end up?',
                'Does SRC keep found items at the counter? Asking so people know where to check first when something goes missing.'
            ),
        ],
    },
}


CHINESE_POST_TEMPLATES = {
    'general': {
        BUCKET_ANY: [
            (
                '最近哪个时段比较舒服？',
                '想找一个不用太赶的时间练基础动作。大家觉得午后、傍晚还是晚饭后更适合放松游？'
            ),
            (
                '泳道一般开几条？',
                '想问问大家平时去的时候泳道够不够用，会不会有几条被课程或者训练占掉？'
            ),
            (
                '大家出发前会看状态卡吗？',
                '首页那个闪电距离和状态卡挺好用的。好奇大家去泳池之前都怎么判断天气合不合适？'
            ),
        ],
        BUCKET_MORNING: [
            (
                '早场泳池人多吗？',
                '第一节没课，想趁早上去游一会儿。有刚路过或者在泳池的同学说下现在的情况吗？'
            ),
            (
                '上午想去慢慢游',
                '上午没什么安排，想去舒服地游几圈。早上这个时段一般人多不多？'
            ),
        ],
        BUCKET_MIDDAY: [
            (
                '中午去游泳晒不晒？',
                '午休想去游一会儿，就是担心太阳太大。中午去过的同学感觉怎么样？'
            ),
            (
                '下午泳池状态小问',
                '看天气好像还可以，如果雨不大就想下午去一趟。有人知道现在池边人多不多、适不适合慢慢游吗？'
            ),
        ],
        BUCKET_EVENING: [
            (
                '今晚 SRC 泳池人多吗？',
                '想晚点去轻松游几圈，不太想赶在人最多的时候。有没有刚路过的同学可以说一下泳道情况？'
            ),
            (
                '闭馆前人会少一点吗？',
                '想挑个安静点的时段，晚上靠近闭馆的时候是不是人比较少？有经验的同学分享一下。'
            ),
        ],
    },
    'squad': {
        BUCKET_ANY: [
            (
                '新手友好泳道搭子招募',
                '有没有同学想组个随缘小队？主要是互相提醒坚持一下，游累了停下来聊天也完全可以。'
            ),
            (
                '周末有人约游泳吗？',
                '周六周日都可以，想找人一起慢慢游，顺便养成习惯。速度不重要，重在坚持。'
            ),
        ],
        BUCKET_MORNING: [
            (
                '早场搭子有吗？',
                '想趁早上人少去游一会儿，有没有同学也喜欢早场？可以约着一起，互相监督早起。'
            ),
        ],
        BUCKET_MIDDAY: [
            (
                '午休游泳搭子招募',
                '中午有空档，想去游个半小时再回来上课。有时间合适的同学可以一起，配速随意。'
            ),
        ],
        BUCKET_EVENING: [
            (
                '晚饭后有人一起轻松游吗？',
                '我大概想游 30 分钟左右，慢速也没关系，中间休息也可以。想找一个不卷的搭子一起下水。'
            ),
            (
                '今晚简单游几组？',
                '准备先热身几趟，再游几个轻松 50 米，最后慢慢放松。有人时间差不多的话可以一起。'
            ),
        ],
    },
    'tutorial': {
        BUCKET_ANY: [
            (
                '自由泳换气小心得',
                '最近发现不要憋到最后一秒再换气会舒服很多，水下慢慢吐气，抬头那一下就没那么慌。'
            ),
            (
                '打腿练习提醒',
                '拿浮板慢慢打几趟其实挺有用的，重点不是水花大，而是动作小一点、节奏稳一点。'
            ),
            (
                '短时间游泳也要热身',
                '就算只游半小时，我也会先慢慢游四趟再加一点速度。身体打开之后，后面会顺很多。'
            ),
            (
                '蛙泳蹬腿总感觉不对',
                '练了一阵才意识到收腿要慢、蹬夹要连贯。有没有同学有简单的纠正办法可以分享？'
            ),
            (
                '游完肩膀酸的小缓解',
                '游完拉伸一下肩膀和背，第二天会舒服很多。分享给同样容易肩膀酸的同学。'
            ),
        ],
    },
    'lostfound': {
        BUCKET_ANY: [
            (
                '泳池失物招领提醒',
                '如果今天有人看到泳镜、泳帽或者毛巾落在池边，可以顺手在这里说一声，失主应该会很感谢。'
            ),
            (
                '离开前记得看一眼长椅',
                '游完最容易忘小东西了，尤其是泳镜和帽子。大家走之前可以多检查一下包和淋浴区。'
            ),
            (
                '捡到的东西一般交去哪里？',
                '想问问大家，在泳池捡到别人落下的东西一般交到哪里？知道的话丢东西的同学也好去找。'
            ),
        ],
    },
}


# Comment templates by post category -> language -> [comment, ...].
COMMENT_TEMPLATES = {
    'general': {
        'zh': [
            '同问，蹲一个现场情况。',
            '我一般避开高峰去，感觉会舒服一些。',
            '可以先看下首页的实时状态再出发，挺准的。',
            '蹲个后续，问得好。',
            '同好奇，有去过的同学说说吗？',
        ],
        'en': [
            'Following this, curious too.',
            'Usually calmer outside peak hours in my experience.',
            'Worth checking the live status card on the homepage before heading over.',
            'Good question, hope someone nearby replies.',
            'Also wondering about this.',
        ],
    },
    'squad': {
        'zh': [
            '我也想去，几点出发？',
            '+1，时间合适的话带上我。',
            '可以约，我游得慢，不介意的话一起。',
            '蹲一个，今天不行改天也可以。',
            '这个节奏很适合我，关注了。',
        ],
        'en': [
            'Count me in if it is a slow pace.',
            'What time are you thinking?',
            '+1, I am usually free around then.',
            'Keen to join if the weather holds.',
            'This pace sounds right for me.',
        ],
    },
    'tutorial': {
        'zh': [
            '这个提醒有用，收藏了。',
            '学到了，下次下水试试。',
            '我也是这样练的，确实有效果。',
            '补充一点：节奏比力量重要。',
            '谢谢分享，正好需要。',
        ],
        'en': [
            'Nice tip, saving this.',
            'Tried something similar and it helped a lot.',
            'Adding this to my next session.',
            'Agree, rhythm over power.',
            'Thanks for sharing this.',
        ],
    },
    'lostfound': {
        'zh': [
            '帮顶，希望失主看到。',
            '可以问问前台有没有人交上去。',
            '帮忙顶一下。',
        ],
        'en': [
            'Bumping this for visibility.',
            'Maybe check with the SRC counter too.',
            'Hope the owner sees this.',
        ],
    },
}


def _bot_avatar_url(persona_key, index):
    source, style = BOT_AVATAR_SOURCES[index % len(BOT_AVATAR_SOURCES)]
    seed = f'ntupool-{persona_key}'
    if source == 'picsum':
        return f'https://picsum.photos/seed/{seed}/96/96'
    if source == 'loremflickr':
        return f'https://loremflickr.com/96/96/{style}?lock={1000 + index}'

    background = BOT_AVATAR_COLORS[index % len(BOT_AVATAR_COLORS)]
    return f'https://api.dicebear.com/10.x/{style}/svg?seed={seed}&backgroundColor={background}&radius=50'


def _sgt_day(now):
    return (now + SGT_OFFSET).date().isoformat()


def _day_bounds_utc(day):
    start_sgt = datetime.fromisoformat(day)
    start_utc = start_sgt - SGT_OFFSET
    return start_utc, start_utc + timedelta(days=1)


def _time_bucket(now):
    """Return the SGT time-of-day bucket for a naive-UTC datetime."""
    sgt_hour = ((now + SGT_OFFSET).time()).hour
    if sgt_hour < 11:
        return BUCKET_MORNING
    if sgt_hour < 16:
        return BUCKET_MIDDAY
    return BUCKET_EVENING


def _scattered_timestamp(now):
    """Return `now` minus a small random offset so activity avoids :00/:30."""
    return now - timedelta(
        minutes=random.randint(0, MAX_TIMESTAMP_SCATTER_MINUTES),
        seconds=random.randint(0, 59),
    )


def _contains_cjk(text):
    return any('一' <= char <= '鿿' for char in text or '')


def _post_language(post):
    return 'zh' if _contains_cjk(f'{post.title or ""}{post.body or ""}') else 'en'


def _bot_language(account):
    return 'zh' if account.persona_key in CHINESE_PERSONA_KEYS else 'en'


def ensure_bot_accounts(now=None):
    now = now or datetime.utcnow()

    # Fast path: skip the 50-account sync when everything is already seeded.
    expected = len(BOT_PERSONAS)
    if (
        BotAccount.query.count() == expected
        and User.query.filter_by(is_bot=True).count() == expected
    ):
        return {'created': 0, 'updated': 0, 'skipped': True}

    created = 0
    updated = 0

    for index, (persona_key, display_name, archetype, voice) in enumerate(BOT_PERSONAS):
        username = f'bot_{persona_key}'
        email = f'{username}@ntupool.local'
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(
                email=email,
                username=username,
                is_verified=True,
                is_bot=True,
                bot_persona=persona_key,
                nickname=display_name,
            )
            db.session.add(user)
            db.session.flush()
        else:
            user.is_verified = True
            user.is_bot = True
            user.bot_persona = persona_key
            user.nickname = display_name
        user.avatar_url = _bot_avatar_url(persona_key, index)

        account = BotAccount.query.filter_by(persona_key=persona_key).first()
        if account is None:
            account = BotAccount(
                user_id=user.id,
                persona_key=persona_key,
                display_name=display_name,
                archetype=archetype,
                voice=voice,
                enabled=True,
                next_run_at=now,
            )
            db.session.add(account)
            created += 1
        else:
            account.user_id = user.id
            account.display_name = display_name
            account.archetype = archetype
            account.voice = voice
            account.enabled = True
            updated += 1

    db.session.commit()
    return {'created': created, 'updated': updated}


def get_or_create_daily_plan(now=None):
    now = now or datetime.utcnow()
    day = _sgt_day(now)
    plan = BotDailyPostPlan.query.filter_by(day=day).first()
    if plan is None:
        plan = BotDailyPostPlan(
            day=day,
            target_count=random.randint(DAILY_MIN_POSTS, DAILY_MAX_POSTS),
            report_target_count=random.randint(DAILY_MIN_REPORTS, DAILY_MAX_REPORTS),
            comment_target_count=random.randint(DAILY_MIN_COMMENTS, DAILY_MAX_COMMENTS),
            like_target_count=random.randint(DAILY_MIN_LIKES, DAILY_MAX_LIKES),
        )
        db.session.add(plan)
        db.session.commit()
        return plan

    # Backfill targets on plans created before these columns existed.
    changed = False
    if plan.report_target_count is None:
        plan.report_target_count = random.randint(DAILY_MIN_REPORTS, DAILY_MAX_REPORTS)
        changed = True
    if plan.comment_target_count is None:
        plan.comment_target_count = random.randint(DAILY_MIN_COMMENTS, DAILY_MAX_COMMENTS)
        changed = True
    if plan.like_target_count is None:
        plan.like_target_count = random.randint(DAILY_MIN_LIKES, DAILY_MAX_LIKES)
        changed = True
    if changed:
        db.session.commit()
    return plan


def _action_count_for_day(day, action_type):
    start_utc, end_utc = _day_bounds_utc(day)
    return BotActivityLog.query.filter(
        BotActivityLog.action_type == action_type,
        BotActivityLog.status == 'posted',
        BotActivityLog.created_at >= start_utc,
        BotActivityLog.created_at < end_utc,
    ).count()


def _posted_count_for_day(day):
    return _action_count_for_day(day, ACTION_CREATE_POST)


def _remaining_ticks(now, window_end):
    remaining_seconds = max(0.0, (window_end - now).total_seconds())
    return max(1, int(remaining_seconds // (TICK_INTERVAL_MINUTES * 60)) + 1)


def _should_act_this_tick(remaining_actions, now, window_end):
    """Randomly gate one action so the daily target spreads over the window."""
    if remaining_actions <= 0:
        return False
    probability = min(1.0, remaining_actions / _remaining_ticks(now, window_end))
    return random.random() < probability


def _select_account(now):
    accounts = BotAccount.query.filter_by(enabled=True).all()
    if not accounts:
        return None

    due_accounts = [
        account for account in accounts
        if account.next_run_at is None or account.next_run_at <= now
    ]
    if not due_accounts:
        return None

    latest_log = BotActivityLog.query.filter_by(
        action_type=ACTION_CREATE_POST,
        status='posted',
    ).order_by(BotActivityLog.created_at.desc()).first()
    if latest_log and len(due_accounts) > 1:
        due_accounts = [
            account for account in due_accounts
            if account.id != latest_log.bot_account_id
        ] or due_accounts

    return random.choice(due_accounts)


def _recent_bot_post_titles(now):
    cutoff = now - timedelta(days=TEMPLATE_REUSE_LOOKBACK_DAYS)
    rows = (
        db.session.query(Post.title)
        .join(User, Post.author_id == User.id)
        .filter(User.is_bot.is_(True), Post.created_at >= cutoff)
        .all()
    )
    return {row.title for row in rows}


def _template_candidates(account, bucket):
    template_source = (
        CHINESE_POST_TEMPLATES
        if account.persona_key in CHINESE_PERSONA_KEYS
        else POST_TEMPLATES
    )
    buckets = template_source.get(account.archetype) or template_source['general']
    candidates = list(buckets.get(BUCKET_ANY, []))
    candidates.extend(buckets.get(bucket, []))
    return candidates


def _build_post(account, now=None):
    """Pick a template matching the bot's language and the SGT time of day.

    Titles used by any bot within the reuse window are avoided while
    alternatives exist, so the feed does not show duplicate topics.
    """
    now = now or datetime.utcnow()
    candidates = _template_candidates(account, _time_bucket(now))
    recent_titles = _recent_bot_post_titles(now)
    fresh = [item for item in candidates if item[0] not in recent_titles]
    title, body = random.choice(fresh or candidates)
    return title, body


def _schedule_next_run(account, now):
    account.last_post_at = now
    account.next_run_at = now + timedelta(hours=random.randint(6, 30), minutes=random.randint(0, 55))


def _get_homepage_report_status():
    state, _, _ = weather_engine.get_overall_status()
    return 'Open' if getattr(state, 'value', None) == 'Open' else 'Closed'


def _invalidate_live_status_report_cache():
    try:
        from app.blueprints.live_status import _invalidate_report_cache

        _invalidate_report_cache()
    except Exception:
        pass


def _run_post_action(now, plan, window_end):
    posted_count = _posted_count_for_day(plan.day)
    if posted_count >= plan.target_count:
        return {'action': 'skipped', 'reason': 'daily_target_reached',
                'posted_count': posted_count, 'target_count': plan.target_count}

    if not _should_act_this_tick(plan.target_count - posted_count, now, window_end):
        return {'action': 'skipped', 'reason': 'randomized_wait',
                'posted_count': posted_count, 'target_count': plan.target_count}

    account = _select_account(now)
    if account is None:
        return {'action': 'skipped', 'reason': 'no_due_bot_account',
                'posted_count': posted_count, 'target_count': plan.target_count}

    title, body = _build_post(account, now)
    post_time = _scattered_timestamp(now)
    post = Post(
        title=title,
        body=body,
        category=account.archetype,
        author_id=account.user_id,
        created_at=post_time,
        updated_at=post_time,
    )
    db.session.add(post)
    db.session.flush()
    _schedule_next_run(account, now)
    db.session.add(BotActivityLog(
        bot_account_id=account.id,
        action_type=ACTION_CREATE_POST,
        status='posted',
        post_id=post.id,
        reason=f'daily_plan:{plan.day}:{posted_count + 1}/{plan.target_count}',
        created_at=now,
    ))
    db.session.commit()

    return {
        'action': 'posted',
        'post_id': post.id,
        'bot': account.persona_key,
        'posted_count': posted_count + 1,
        'target_count': plan.target_count,
    }


def _run_report_action(now, plan, window_end, *, exclude_user_id=None):
    """Submit a standalone bot pool report, decoupled from posting."""
    reported_count = _action_count_for_day(plan.day, ACTION_POOL_REPORT)
    target = plan.report_target_count or 0
    if reported_count >= target:
        return {'action': 'skipped', 'reason': 'daily_target_reached',
                'reported_count': reported_count, 'target_count': target}

    if not _should_act_this_tick(target - reported_count, now, window_end):
        return {'action': 'skipped', 'reason': 'randomized_wait',
                'reported_count': reported_count, 'target_count': target}

    accounts = BotAccount.query.filter_by(enabled=True).all()
    latest_report_log = BotActivityLog.query.filter_by(
        action_type=ACTION_POOL_REPORT,
        status='posted',
    ).order_by(BotActivityLog.created_at.desc()).first()

    candidates = [
        account for account in accounts
        if account.user_id != exclude_user_id
        and not (latest_report_log and account.id == latest_report_log.bot_account_id)
    ] or accounts
    if not candidates:
        return {'action': 'skipped', 'reason': 'no_bot_account',
                'reported_count': reported_count, 'target_count': target}

    account = random.choice(candidates)
    status = _get_homepage_report_status()
    db.session.add(PoolReport(
        status=status,
        user_id=account.user_id,
        created_at=_scattered_timestamp(now),
    ))
    db.session.add(BotActivityLog(
        bot_account_id=account.id,
        action_type=ACTION_POOL_REPORT,
        status='posted',
        reason=f'daily_plan:{plan.day}:{reported_count + 1}/{target}:{status}',
        created_at=now,
    ))
    db.session.commit()
    _invalidate_live_status_report_cache()

    return {
        'action': 'posted',
        'bot': account.persona_key,
        'status': status,
        'reported_count': reported_count + 1,
        'target_count': target,
    }


def _bot_user_ids():
    rows = db.session.query(User.id).filter(User.is_bot.is_(True)).all()
    return {row.id for row in rows}


def _cleanup_legacy_duplicate_posts(now):
    """One-time cleanup of duplicate-titled legacy bot posts.

    The pre-2026-07 template pool was small enough that the feed accumulated
    many identical titles. This soft-deletes the extras, keeping per title the
    post with human comments first, then the most-commented, then the newest.
    A post that received human comments is never hidden. A marker row in
    BotActivityLog guarantees the cleanup runs exactly once per database.
    """
    marker = BotActivityLog.query.filter_by(action_type=ACTION_DEDUPE_CLEANUP).first()
    if marker is not None:
        return None

    bot_ids = _bot_user_ids()
    posts = (
        Post.query.filter(
            Post.is_deleted.is_(False),
            Post.author_id.in_(bot_ids),
        ).all()
        if bot_ids
        else []
    )

    post_ids = [post.id for post in posts]
    comment_rows = (
        db.session.query(Comment.post_id, Comment.author_id)
        .filter(Comment.post_id.in_(post_ids), Comment.is_deleted.is_(False))
        .all()
        if post_ids
        else []
    )
    comment_totals = {}
    has_human_comment = {}
    for post_id, author_id in comment_rows:
        comment_totals[post_id] = comment_totals.get(post_id, 0) + 1
        if author_id not in bot_ids:
            has_human_comment[post_id] = True

    groups = {}
    for post in posts:
        title = (post.title or '').strip()
        if title:
            groups.setdefault(title, []).append(post)

    deleted = 0
    for title, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda post: (
                bool(has_human_comment.get(post.id)),
                comment_totals.get(post.id, 0),
                post.created_at or datetime.min,
            ),
            reverse=True,
        )
        for post in group[1:]:
            if has_human_comment.get(post.id):
                # Never hide a thread a real user participated in.
                continue
            post.is_deleted = True
            deleted += 1

    db.session.add(BotActivityLog(
        action_type=ACTION_DEDUPE_CLEANUP,
        status='posted',
        reason=f'legacy_duplicate_posts_removed:{deleted}',
        created_at=now,
    ))
    db.session.commit()
    return {'deleted': deleted}


def _comment_counts(post_ids, bot_ids):
    """Return ({post_id: total_comments}, {post_id: bot_comments})."""
    if not post_ids:
        return {}, {}
    rows = (
        db.session.query(Comment.post_id, Comment.author_id)
        .filter(Comment.post_id.in_(post_ids), Comment.is_deleted.is_(False))
        .all()
    )
    totals = {}
    bot_totals = {}
    for post_id, author_id in rows:
        totals[post_id] = totals.get(post_id, 0) + 1
        if author_id in bot_ids:
            bot_totals[post_id] = bot_totals.get(post_id, 0) + 1
    return totals, bot_totals


def _select_comment_target(now, bot_ids):
    """Pick a post worth replying to.

    Priority: human posts with no replies at all, then quiet human posts,
    then unanswered recent bot posts (so threads do not look dead).
    """
    human_cutoff = now - HUMAN_POST_LOOKBACK
    bot_cutoff = now - BOT_POST_LOOKBACK
    posts = (
        Post.query.filter(
            Post.is_deleted.is_(False),
            Post.created_at >= min(human_cutoff, bot_cutoff),
        )
        .order_by(Post.created_at.desc())
        .limit(60)
        .all()
    )
    if not posts:
        return None

    totals, bot_totals = _comment_counts([post.id for post in posts], bot_ids)

    lonely_human = []
    quiet_human = []
    lonely_bot = []
    for post in posts:
        total = totals.get(post.id, 0)
        bots_here = bot_totals.get(post.id, 0)
        is_bot_post = post.author_id in bot_ids
        if not is_bot_post and post.created_at >= human_cutoff:
            if total == 0:
                lonely_human.append(post)
            elif total < MAX_TOTAL_COMMENTS_FOR_TARGET and bots_here < MAX_BOT_COMMENTS_PER_POST:
                quiet_human.append(post)
        elif is_bot_post and post.created_at >= bot_cutoff and total == 0:
            lonely_bot.append(post)

    for pool in (lonely_human, quiet_human, lonely_bot):
        if pool:
            return random.choice(pool)
    return None


def _select_commenting_account(post, bot_ids):
    language = _post_language(post)
    accounts = BotAccount.query.filter_by(enabled=True).all()
    already_commented = {
        row.author_id
        for row in db.session.query(Comment.author_id)
        .filter(Comment.post_id == post.id, Comment.is_deleted.is_(False))
        .all()
    }
    candidates = [
        account for account in accounts
        if account.user_id != post.author_id
        and account.user_id not in already_commented
        and _bot_language(account) == language
    ]
    if not candidates:
        return None
    return random.choice(candidates)


def _run_comment_action(now, plan, window_end):
    commented_count = _action_count_for_day(plan.day, ACTION_CREATE_COMMENT)
    target = plan.comment_target_count or 0
    if commented_count >= target:
        return {'action': 'skipped', 'reason': 'daily_target_reached',
                'commented_count': commented_count, 'target_count': target}

    if not _should_act_this_tick(target - commented_count, now, window_end):
        return {'action': 'skipped', 'reason': 'randomized_wait',
                'commented_count': commented_count, 'target_count': target}

    bot_ids = _bot_user_ids()
    post = _select_comment_target(now, bot_ids)
    if post is None:
        return {'action': 'skipped', 'reason': 'no_target_post',
                'commented_count': commented_count, 'target_count': target}

    account = _select_commenting_account(post, bot_ids)
    if account is None:
        return {'action': 'skipped', 'reason': 'no_matching_bot',
                'commented_count': commented_count, 'target_count': target}

    language = _post_language(post)
    templates = COMMENT_TEMPLATES.get(post.category or 'general') or COMMENT_TEMPLATES['general']
    body = random.choice(templates.get(language) or templates['en'])

    comment = Comment(
        body=body,
        author_id=account.user_id,
        post_id=post.id,
        created_at=_scattered_timestamp(now),
    )
    db.session.add(comment)
    db.session.add(BotActivityLog(
        bot_account_id=account.id,
        action_type=ACTION_CREATE_COMMENT,
        status='posted',
        post_id=post.id,
        reason=f'daily_plan:{plan.day}:{commented_count + 1}/{target}',
        created_at=now,
    ))
    db.session.commit()

    return {
        'action': 'posted',
        'post_id': post.id,
        'bot': account.persona_key,
        'commented_count': commented_count + 1,
        'target_count': target,
    }


def _run_like_action(now, plan, window_end):
    liked_count = _action_count_for_day(plan.day, ACTION_LIKE_POST)
    target = plan.like_target_count or 0
    if liked_count >= target:
        return {'action': 'skipped', 'reason': 'daily_target_reached',
                'liked_count': liked_count, 'target_count': target}

    if not _should_act_this_tick(target - liked_count, now, window_end):
        return {'action': 'skipped', 'reason': 'randomized_wait',
                'liked_count': liked_count, 'target_count': target}

    bot_ids = _bot_user_ids()
    cutoff = now - HUMAN_POST_LOOKBACK
    posts = (
        Post.query.filter(Post.is_deleted.is_(False), Post.created_at >= cutoff)
        .order_by(Post.created_at.desc())
        .limit(60)
        .all()
    )
    if not posts:
        return {'action': 'skipped', 'reason': 'no_target_post',
                'liked_count': liked_count, 'target_count': target}

    accounts = BotAccount.query.filter_by(enabled=True).all()
    random.shuffle(accounts)
    human_posts = [post for post in posts if post.author_id not in bot_ids]
    ordered_posts = human_posts + [post for post in posts if post.author_id in bot_ids]

    for post in ordered_posts:
        candidates = [account for account in accounts if account.user_id != post.author_id]
        for account in candidates:
            existing = Like.query.filter_by(user_id=account.user_id, post_id=post.id).first()
            if existing:
                continue
            db.session.add(Like(
                user_id=account.user_id,
                post_id=post.id,
                created_at=_scattered_timestamp(now),
            ))
            db.session.add(BotActivityLog(
                bot_account_id=account.id,
                action_type=ACTION_LIKE_POST,
                status='posted',
                post_id=post.id,
                reason=f'daily_plan:{plan.day}:{liked_count + 1}/{target}',
                created_at=now,
            ))
            db.session.commit()
            return {
                'action': 'posted',
                'post_id': post.id,
                'bot': account.persona_key,
                'liked_count': liked_count + 1,
                'target_count': target,
            }

    return {'action': 'skipped', 'reason': 'no_unliked_post',
            'liked_count': liked_count, 'target_count': target}


def run_community_post_tick(now=None):
    """One scheduler tick: maybe post, report, comment, and like.

    Backward-compatible top-level keys ('action', 'reason', 'posted_count',
    'target_count') describe the POST action; the report, comment, and like
    outcomes are nested under their own keys.
    """
    now = now or datetime.utcnow()
    ensure_bot_accounts(now=now)

    # Data hygiene runs before the operating-hours gate: it is invisible to
    # users and should complete as soon as possible after deploy.
    cleanup_result = _cleanup_legacy_duplicate_posts(now)

    window = operating_hours.operating_window_utc_naive(
        now, edge_buffer=ACTION_WINDOW_EDGE_BUFFER
    )
    if window is None or not (window[0] <= now < window[1]):
        result = {
            'ok': True,
            'action': 'skipped',
            'reason': 'outside_operating_hours',
        }
        if cleanup_result is not None:
            result['cleanup'] = cleanup_result
        return result
    _, window_end = window

    plan = get_or_create_daily_plan(now=now)

    post_result = _run_post_action(now, plan, window_end)
    report_result = _run_report_action(now, plan, window_end)
    comment_result = _run_comment_action(now, plan, window_end)
    like_result = _run_like_action(now, plan, window_end)

    result = {
        'ok': True,
        'report': report_result,
        'comment': comment_result,
        'like': like_result,
    }
    if cleanup_result is not None:
        result['cleanup'] = cleanup_result
    result.update(post_result)
    return result
