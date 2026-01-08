from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app.extensions import db, mail
from flask_mail import Message
import re
import random
import string
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def is_valid_email(email):
    """Validate email format (accepts any valid email address)."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def generate_otp():
    """Generate a 6-digit OTP."""
    return ''.join(random.choices(string.digits, k=6))

def send_verification_email(user):
    # Determine OTP
    otp = generate_otp()
    user.otp_code = otp
    user.otp_expiry = datetime.utcnow() + timedelta(minutes=10)
    db.session.commit()

    msg = Message('Your NTU Pool Verification Code',
                  sender=current_app.config['MAIL_USERNAME'],
                  recipients=[user.email])
    msg.body = f'Your verification code is: {otp}\n\nThis code expires in 10 minutes.'
    # In production, use a proper HTML template
    try:
        mail.send(msg)
    except Exception as e:
        print(f"Email send error: {e}")
        flash('Error sending verification email. Please try again later.', 'error')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email').lower()
        username = request.form.get('username')
        password = request.form.get('password')
        confirm = request.form.get('password_confirm')

        if not is_valid_email(email):
            flash('Please enter a valid email address.', 'error')
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
        db.session.add(user)
        db.session.commit()

        # Send OTP
        send_verification_email(user)
        
        flash('Account created! Please enter the verification code sent to your email.', 'success')
        login_user(user) # Auto login but restricted
        return redirect(url_for('auth.verify_otp'))

    return render_template('auth/register.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email').lower()
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and user.verify_password(password):
            login_user(user)
            if not user.is_verified:
                flash('Please verify your account to continue.', 'warning')
                return redirect(url_for('auth.verify_otp'))
            return redirect(url_for('index'))
        
        flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@auth_bp.route('/verify', methods=['GET', 'POST'])
@login_required
def verify_otp():
    if current_user.is_verified:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        code = request.form.get('otp_code')
        
        if not current_user.otp_code or not current_user.otp_expiry:
             flash('No active verification code. Please request a new one.', 'error')
             return redirect(url_for('auth.verify_otp'))

        if datetime.utcnow() > current_user.otp_expiry:
            flash('Verification code has expired.', 'error')
            return redirect(url_for('auth.verify_otp'))
            
        if code == current_user.otp_code:
            current_user.is_verified = True
            current_user.otp_code = None
            current_user.otp_expiry = None
            db.session.commit()
            flash('Account verified! Welcome to the community.', 'success')
            return redirect(url_for('index'))
        else:
             flash('Invalid verification code. Please try again.', 'error')

    return render_template('auth/verify_otp.html')

@auth_bp.route('/resend')
@login_required
def resend_confirmation():
    if current_user.is_verified:
        return redirect(url_for('index'))
        
    send_verification_email(current_user)
    flash('A new verification code has been sent to your email.', 'success')
    return redirect(url_for('auth.verify_otp'))

# Deprecated/Legacy routes (keeping placeholders to avoid 404s if linked elsewhere or clean up)
@auth_bp.route('/unverified')
def unverified():
    return redirect(url_for('auth.verify_otp'))

@auth_bp.route('/confirm/<token>')
def confirm_email(token):
    flash('The link verification system has been deprecated. Please login and use OTP.', 'info')
    return redirect(url_for('auth.login'))



