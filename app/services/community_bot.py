import random
from datetime import datetime, timedelta

from app.extensions import db
from app.models.bot import BotAccount, BotActivityLog, BotDailyPostPlan
from app.models.content import Post
from app.models.user import User


SGT_OFFSET = timedelta(hours=8)
DAILY_MIN_POSTS = 2
DAILY_MAX_POSTS = 6


BOT_PERSONAS = [
    ('avery_laps', 'Avery Tan', 'squad', 'casual planner who likes evening laps'),
    ('ben_easy_pace', 'Ben Lim', 'squad', 'beginner-friendly lane buddy'),
    ('chloe_kickboard', 'Chloe Ng', 'tutorial', 'patient technique note-taker'),
    ('daniel_src', 'Daniel Koh', 'general', 'regular who asks practical pool questions'),
    ('emily_splits', 'Emily Wong', 'tutorial', 'pace-focused swimmer'),
    ('farah_swims', 'Farah Rahman', 'squad', 'friendly meetup organizer'),
    ('gabriel_lane4', 'Gabriel Lee', 'general', 'quiet weekday swimmer'),
    ('hannah_pullbuoy', 'Hannah Chia', 'tutorial', 'shares small drills'),
    ('isaac_afterclass', 'Isaac Goh', 'squad', 'after-class swim buddy'),
    ('jasmine_poolbag', 'Jasmine Teo', 'lostfound', 'keeps an eye on lost items'),
    ('kai_warmup', 'Kai Chen', 'tutorial', 'warmup and recovery voice'),
    ('leah_morning', 'Leah Tan', 'squad', 'morning swim regular'),
    ('marcus_ntu', 'Marcus Ong', 'general', 'asks about crowd and lane conditions'),
    ('nina_freestyle', 'Nina Ho', 'tutorial', 'freestyle learner'),
    ('owen_sprints', 'Owen Yap', 'squad', 'short-set swimmer'),
    ('priya_lanes', 'Priya Menon', 'general', 'friendly community checker'),
    ('quentin_pool', 'Quentin Low', 'lostfound', 'lost-and-found reminder'),
    ('rachel_easy', 'Rachel Seah', 'squad', 'easy pace organizer'),
    ('sam_strokes', 'Sam Tan', 'tutorial', 'stroke basics sharer'),
    ('tessa_src', 'Tessa Lim', 'general', 'weather-aware pool regular'),
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

    for persona_key, display_name, archetype, voice in BOT_PERSONAS:
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
    templates = POST_TEMPLATES.get(account.archetype) or POST_TEMPLATES['general']
    title, body = random.choice(templates)
    return title, body


def _schedule_next_run(account, now):
    account.last_post_at = now
    account.next_run_at = now + timedelta(hours=random.randint(6, 30), minutes=random.randint(0, 55))


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
    db.session.commit()

    return {
        'ok': True,
        'action': 'posted',
        'post_id': post.id,
        'bot': account.persona_key,
        'target_count': plan.target_count,
        'posted_count': posted_count + 1,
    }
