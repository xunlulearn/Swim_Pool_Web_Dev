import random
from datetime import datetime, timedelta

from app.extensions import db
from app.models.bot import BotAccount, BotActivityLog, BotDailyPostPlan
from app.models.content import Post
from app.models.report import PoolReport
from app.models.user import User
from app.services.weather_engine import weather_engine


SGT_OFFSET = timedelta(hours=8)
DAILY_MIN_POSTS = 2
DAILY_MAX_POSTS = 6
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


POST_TEMPLATES = {
    'general': [
        (
            'How busy has SRC pool been lately?',
            'I am trying to figure out the calmer windows this week. Has anyone noticed whether late afternoon or after dinner feels less crowded?'
        ),
        (
            'Quick pool check for today',
            'Planning a short swim later if the weather stays reasonable. If anyone passes by SRC, a quick crowd update would be helpful.'
        ),
        (
            'Best time for a relaxed swim?',
            'For people who prefer easy laps without rushing, which time slot has felt the most comfortable recently?'
        ),
    ],
    'squad': [
        (
            'Easy pace swim later?',
            'I am thinking of doing 30-40 minutes at a relaxed pace. Anyone else aiming for a simple no-pressure session?'
        ),
        (
            'Looking for beginner-friendly lane buddies',
            'Would anyone be interested in a casual swim group where stopping between sets is totally fine?'
        ),
        (
            'Short evening set idea',
            'Maybe 200 warmup, a few relaxed 50s, then easy cooldown. Happy to join if someone is planning something similar.'
        ),
    ],
    'tutorial': [
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
    ],
    'lostfound': [
        (
            'Lost-and-found check',
            'If anyone spots goggles, caps, or towels left near the pool area today, maybe drop a note here so the owner has a better chance of finding them.'
        ),
        (
            'Pool bag reminder',
            'Tiny reminder to check the bench and shower area before leaving. Goggles and caps seem very easy to forget after a swim.'
        ),
    ],
}


CHINESE_POST_TEMPLATES = {
    'general': [
        (
            '今天 SRC 泳池人多吗？',
            '想晚点去轻松游几圈，不太想赶在人最多的时候。有没有刚路过的同学可以说一下泳道情况？'
        ),
        (
            '下午泳池状态小问',
            '看天气好像还可以，如果雨不大就想去一趟。有人知道现在池边人多不多、适不适合慢慢游吗？'
        ),
        (
            '最近哪个时段比较舒服？',
            '想找一个不用太赶的时间练基础动作。大家觉得午后、傍晚还是晚饭后更适合放松游？'
        ),
    ],
    'squad': [
        (
            '晚饭后有人一起轻松游吗？',
            '我大概想游 30 分钟左右，慢速也没关系，中间休息也可以。想找一个不卷的搭子一起下水。'
        ),
        (
            '新手友好泳道搭子招募',
            '有没有同学想组个随缘小队？主要是互相提醒坚持一下，游累了停下来聊天也完全可以。'
        ),
        (
            '今晚简单游几组？',
            '准备先热身几趟，再游几个轻松 50 米，最后慢慢放松。有人时间差不多的话可以一起。'
        ),
    ],
    'tutorial': [
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
    ],
    'lostfound': [
        (
            '泳池失物招领提醒',
            '如果今天有人看到泳镜、泳帽或者毛巾落在池边，可以顺手在这里说一声，失主应该会很感谢。'
        ),
        (
            '离开前记得看一眼长椅',
            '游完最容易忘小东西了，尤其是泳镜和帽子。大家走之前可以多检查一下包和淋浴区。'
        ),
    ],
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


def ensure_bot_accounts(now=None):
    now = now or datetime.utcnow()
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
        )
        db.session.add(plan)
        db.session.commit()
    return plan


def _posted_count_for_day(day):
    start_utc, end_utc = _day_bounds_utc(day)
    return BotActivityLog.query.filter(
        BotActivityLog.action_type == 'create_post',
        BotActivityLog.status == 'posted',
        BotActivityLog.created_at >= start_utc,
        BotActivityLog.created_at < end_utc,
    ).count()


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
        action_type='create_post',
        status='posted',
    ).order_by(BotActivityLog.created_at.desc()).first()
    if latest_log and len(due_accounts) > 1:
        due_accounts = [
            account for account in due_accounts
            if account.id != latest_log.bot_account_id
        ] or due_accounts

    return random.choice(due_accounts)


def _build_post(account):
    template_source = CHINESE_POST_TEMPLATES if account.persona_key in CHINESE_PERSONA_KEYS else POST_TEMPLATES
    templates = template_source.get(account.archetype) or template_source['general']
    title, body = random.choice(templates)
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


def run_community_post_tick(now=None):
    now = now or datetime.utcnow()
    ensure_bot_accounts(now=now)
    plan = get_or_create_daily_plan(now=now)
    posted_count = _posted_count_for_day(plan.day)

    if posted_count >= plan.target_count:
        return {
            'ok': True,
            'action': 'skipped',
            'reason': 'daily_target_reached',
            'target_count': plan.target_count,
            'posted_count': posted_count,
        }

    account = _select_account(now)
    if account is None:
        return {
            'ok': True,
            'action': 'skipped',
            'reason': 'no_due_bot_account',
            'target_count': plan.target_count,
            'posted_count': posted_count,
        }

    title, body = _build_post(account)
    report_status = _get_homepage_report_status()
    post = Post(
        title=title,
        body=body,
        category=account.archetype,
        author_id=account.user_id,
        created_at=now,
        updated_at=now,
    )
    db.session.add(post)
    db.session.flush()
    _schedule_next_run(account, now)
    db.session.add(BotActivityLog(
        bot_account_id=account.id,
        action_type='create_post',
        status='posted',
        post_id=post.id,
        reason=f'daily_plan:{plan.day}:{posted_count + 1}/{plan.target_count}',
        created_at=now,
    ))
    db.session.add(PoolReport(
        status=report_status,
        user_id=account.user_id,
        created_at=now,
    ))
    db.session.commit()
    _invalidate_live_status_report_cache()

    return {
        'ok': True,
        'action': 'posted',
        'post_id': post.id,
        'bot': account.persona_key,
        'target_count': plan.target_count,
        'posted_count': posted_count + 1,
    }
