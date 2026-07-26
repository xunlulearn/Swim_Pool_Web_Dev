from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from datetime import datetime, timedelta
import re
import secrets

from app.models.user import User
from app.extensions import db, mail


auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_LOCK_MINUTES = 15
OTP_RESEND_COOLDOWN_SECONDS = 60
MIN_PASSWORD_LENGTH = 8


def now_utc():
    return datetime.utcnow()


def normalize_email(raw_email):
    return (raw_email or '').strip().lower()


def clear_otp_state():
    for key in ('otp_flow', 'otp_email', 'otp_user_id', 'otp_attempts', 'otp_lock_until'):
        session.pop(key, None)


def set_otp_state(flow, email, user_id=None):
    session['otp_flow'] = flow
    session['otp_email'] = email
    session['otp_user_id'] = user_id
    session['otp_attempts'] = 0
    session.pop('otp_lock_until', None)


def get_otp_lock_until():
    lock_until = session.get('otp_lock_until')
    if not lock_until:
        return None
    try:
        return datetime.fromisoformat(lock_until)
    except (TypeError, ValueError):
        session.pop('otp_lock_until', None)
        return None


def is_otp_locked():
    lock_until = get_otp_lock_until()
    return bool(lock_until and now_utc() < lock_until)


def otp_lock_remaining_minutes():
    lock_until = get_otp_lock_until()
    if not lock_until:
        return 0
    remaining_seconds = int((lock_until - now_utc()).total_seconds())
    if remaining_seconds <= 0:
        return 0
    return max(1, (remaining_seconds + 59) // 60)


def register_failed_otp_attempt(user=None):
    attempts = int(session.get('otp_attempts', 0)) + 1
    session['otp_attempts'] = attempts
    if attempts < OTP_MAX_ATTEMPTS:
        return False

    session['otp_lock_until'] = (now_utc() + timedelta(minutes=OTP_LOCK_MINUTES)).isoformat()
    if user:
        user.otp_code = None
        user.otp_expiry = None
        db.session.commit()
    return True


def is_valid_password(password):
    return bool(password) and len(password) >= MIN_PASSWORD_LENGTH


def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email or '') is not None


def generate_otp():
    return f"{secrets.randbelow(1000000):06d}"


def send_verification_email(user):
    otp = generate_otp()
    user.otp_code = otp
    user.otp_expiry = now_utc() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    db.session.commit()
    set_otp_state('verify', user.email, user.id)

    msg = Message(
        'Your NTU Pool Verification Code',
        sender=current_app.config['MAIL_USERNAME'],
        recipients=[user.email],
    )
    msg.body = f'Your verification code is: {otp}\n\nThis code expires in {OTP_EXPIRY_MINUTES} minutes.'
    try:
        mail.send(msg)
    except Exception:
        current_app.logger.exception('Failed to send verification email.')
        flash('Error sending verification email. Please try again later.', 'error')


def send_password_reset_email(user):
    otp = generate_otp()
    user.otp_code = otp
    user.otp_expiry = now_utc() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    db.session.commit()
    set_otp_state('reset', user.email, user.id)

    msg = Message(
        'Password Reset Request - NTU Pool',
        sender=current_app.config['MAIL_USERNAME'],
        recipients=[user.email],
    )
    msg.body = (
        f'Your password reset code is: {otp}\n\n'
        f'This code expires in {OTP_EXPIRY_MINUTES} minutes.\n'
        'If you did not request this, please ignore this email.'
    )
    try:
        mail.send(msg)
    except Exception:
        current_app.logger.exception('Failed to send password reset email.')
        flash('Error sending email. Please try again later.', 'error')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = normalize_email(request.form.get('email'))
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        confirm = request.form.get('password_confirm') or ''

        if not is_valid_email(email):
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('auth.register'))

        if not username:
            flash('Username is required.', 'error')
            return redirect(url_for('auth.register'))

        if not is_valid_password(password):
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'error')
            return redirect(url_for('auth.register'))

        user = User(email=email, username=username)
        user.password = password
        user.nickname = username
        db.session.add(user)
        db.session.commit()

        send_verification_email(user)

        flash('Account created! Please enter the verification code sent to your email.', 'success')
        login_user(user)
        return redirect(url_for('auth.verify_otp'))

    return render_template('auth/register.html')


@auth_bp.route('/password/reset-request', methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        email = normalize_email(request.form.get('email'))
        user = User.query.filter_by(email=email).first() if is_valid_email(email) else None

        if user:
            send_password_reset_email(user)
        else:
            set_otp_state('reset', email, None)

        flash('If an account exists with that email, a verification code has been sent.', 'info')
        return redirect(url_for('auth.reset_password'))

    if session.get('otp_flow') == 'reset':
        email_value = session.get('otp_email') or ''
    elif current_user.is_authenticated:
        email_value = current_user.email
    else:
        email_value = ''

    return render_template('auth/reset_request.html', email_value=email_value)


@auth_bp.route('/password/reset', methods=['GET', 'POST'])
def reset_password():
    if session.get('otp_flow') != 'reset':
        if current_user.is_authenticated:
            set_otp_state('reset', current_user.email, current_user.id)
        else:
            flash('Session expired. Please request password reset again.', 'warning')
            return redirect(url_for('auth.reset_request'))

    email = session.get('otp_email') or ''
    if not email:
        flash('Session expired. Please request password reset again.', 'warning')
        return redirect(url_for('auth.reset_request'))

    if is_otp_locked() and request.method == 'POST':
        flash(
            f'Too many failed attempts. Try again in {otp_lock_remaining_minutes()} minute(s).',
            'error',
        )
        return redirect(url_for('auth.reset_password'))

    if request.method == 'POST':
        otp = (request.form.get('otp') or '').strip()
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm') or ''

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth.reset_password'))

        if not is_valid_password(password):
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.', 'error')
            return redirect(url_for('auth.reset_password'))

        user = User.query.filter_by(email=email).first()

        is_invalid = False
        if not user:
            is_invalid = True
        elif session.get('otp_user_id') not in (None, user.id):
            is_invalid = True
        elif not user.otp_code or not user.otp_expiry:
            is_invalid = True
        elif now_utc() > user.otp_expiry:
            is_invalid = True
        elif user.otp_code != otp:
            is_invalid = True

        if is_invalid:
            is_locked = register_failed_otp_attempt(user=user)
            if is_locked:
                flash(
                    f'Too many failed attempts. Try again in {otp_lock_remaining_minutes()} minute(s).',
                    'error',
                )
            else:
                flash('Verification code expired or invalid.', 'error')
            return redirect(url_for('auth.reset_password'))

        user.password = password
        user.otp_code = None
        user.otp_expiry = None
        db.session.commit()

        clear_otp_state()
        flash('Your password has been updated! Please login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = normalize_email(request.form.get('email'))
        password = request.form.get('password') or ''

        if not email or not password:
            flash('Invalid email or password.', 'error')
            return render_template('auth/login.html')

        user = User.query.filter_by(email=email).first()

        if user and user.verify_password(password):
            login_user(user)
            if not user.is_verified:
                flash('Please verify your account to continue.', 'warning')
                return redirect(url_for('auth.verify_otp'))
            return redirect(url_for('index'))

        flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    clear_otp_state()
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


@auth_bp.route('/verify', methods=['GET', 'POST'])
@login_required
def verify_otp():
    if current_user.is_verified:
        return redirect(url_for('index'))

    if request.method == 'POST':
        if session.get('otp_flow') != 'verify' or session.get('otp_user_id') != current_user.id:
            flash('No active verification code. Please request a new one.', 'error')
            return redirect(url_for('auth.verify_otp'))

        if is_otp_locked():
            flash(
                f'Too many failed attempts. Try again in {otp_lock_remaining_minutes()} minute(s).',
                'error',
            )
            return redirect(url_for('auth.verify_otp'))

        code = (request.form.get('otp_code') or '').strip()

        if not current_user.otp_code or not current_user.otp_expiry:
            flash('No active verification code. Please request a new one.', 'error')
            return redirect(url_for('auth.verify_otp'))

        if now_utc() > current_user.otp_expiry:
            current_user.otp_code = None
            current_user.otp_expiry = None
            db.session.commit()
            flash('Verification code has expired.', 'error')
            return redirect(url_for('auth.verify_otp'))

        if code == current_user.otp_code:
            current_user.is_verified = True
            current_user.otp_code = None
            current_user.otp_expiry = None
            db.session.commit()
            clear_otp_state()
            flash('Account verified! Welcome to the community.', 'success')
            return redirect(url_for('index'))

        is_locked = register_failed_otp_attempt(user=current_user)
        if is_locked:
            flash(
                f'Too many failed attempts. Try again in {otp_lock_remaining_minutes()} minute(s).',
                'error',
            )
        else:
            flash('Invalid verification code. Please try again.', 'error')

    return render_template('auth/verify_otp.html')


@auth_bp.route('/resend', methods=['POST'])
@login_required
def resend_confirmation():
    if current_user.is_verified:
        return redirect(url_for('index'))

    if is_otp_locked():
        flash(
            f'Too many failed attempts. Try again in {otp_lock_remaining_minutes()} minute(s).',
            'error',
        )
        return redirect(url_for('auth.verify_otp'))

    # Cooldown between resends: protects mail quota and sender reputation.
    last_sent_raw = session.get('otp_last_sent_at')
    if last_sent_raw:
        try:
            last_sent = datetime.fromisoformat(last_sent_raw)
        except (TypeError, ValueError):
            last_sent = None
        if last_sent is not None:
            elapsed = (now_utc() - last_sent).total_seconds()
            if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
                wait_seconds = int(OTP_RESEND_COOLDOWN_SECONDS - elapsed) + 1
                flash(
                    f'Please wait {wait_seconds} second(s) before requesting another code.',
                    'warning',
                )
                return redirect(url_for('auth.verify_otp'))

    send_verification_email(current_user)
    session['otp_last_sent_at'] = now_utc().isoformat()
    flash('A new verification code has been sent to your email.', 'success')
    return redirect(url_for('auth.verify_otp'))


@auth_bp.route('/unverified')
def unverified():
    return redirect(url_for('auth.verify_otp'))


@auth_bp.route('/confirm/<token>')
def confirm_email(token):
    flash('The link verification system has been deprecated. Please login and use OTP.', 'info')
    return redirect(url_for('auth.login'))
