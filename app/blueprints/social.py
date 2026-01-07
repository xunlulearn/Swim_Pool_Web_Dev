from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models.content import Post
from app.extensions import db

social_bp = Blueprint('social', __name__, url_prefix='/social')

@social_bp.route('/feed')
@login_required
def feed():
    # Show public posts + friends' posts (simplified to all public for v1)
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('social/feed.html', posts=posts)

@social_bp.route('/post', methods=['POST'])
@login_required
def create_post():
    if not current_user.is_verified:
        flash('You must verify your email to post.', 'error')
        return redirect(url_for('social.feed'))
        
    body = request.form.get('body')
    if not body:
        flash('Post cannot be empty.', 'error')
        return redirect(url_for('social.feed'))
        
    post = Post(body=body, author=current_user)
    db.session.add(post)
    db.session.commit()
    
    flash('Posted successfully!', 'success')
    return redirect(url_for('social.feed'))
