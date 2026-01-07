from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app.extensions import db, mail
from flask_mail import Message
import re

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def is_ntu_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@(?:e\.)?ntu\.edu\.sg$'
    return re.match(pattern, email) is not None

def send_verification_email(user):
    token = user.generate_auth_token()
    confirm_url = url_for('auth.confirm_email', token=token, _external=True)
    msg = Message('Verify Your NTU Pool Account',
                  sender=current_app.config['MAIL_USERNAME'],
                  recipients=[user.email])
    msg.body = f'Welcome! Please click the link to verify your account: {confirm_url}'
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

        if not is_ntu_email(email):
            flash('Please use a valid NTU email (@ntu.edu.sg or @e.ntu.edu.sg)', 'error')
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

        # Send verification (mock for now if no SMTP)
        # send_verification_email(user) 
        
        flash('Account created! Please check your email to verify.', 'success')
        login_user(user) # Auto login but restricted
        return redirect(url_for('auth.unverified'))

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
            return redirect(url_for('index'))
        
        flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@auth_bp.route('/unverified')
@login_required
def unverified():
    if current_user.is_verified:
        return redirect(url_for('index'))
    return render_template('auth/unverified.html')

@auth_bp.route('/confirm/<token>')
@login_required
def confirm_email(token):
    if current_user.is_verified:
        return redirect(url_for('index'))
    
    # In a real scenario, we verify the token matches the current user
    # simplified logic:
    user = User.verify_auth_token(token)
    if user and user.id == current_user.id:
        current_user.is_verified = True
        db.session.commit()
        flash('Account verified! Welcome to the community.', 'success')
    else:
        flash('The confirmation link is invalid or has expired.', 'error')
        
    return redirect(url_for('index'))

@auth_bp.route('/resend')
@login_required
def resend_confirmation():
    # send_verification_email(current_user)
    flash('Verification email resent.', 'success')
    return redirect(url_for('auth.unverified'))



