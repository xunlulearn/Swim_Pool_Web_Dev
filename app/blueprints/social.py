from functools import wraps
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, abort
from flask_login import login_required, current_user
from app.models.content import Post, Comment
from app.models.interaction import Like, Collection
from app.models.content_report import ContentReport
from app.models.user import User
from app.extensions import db

social_bp = Blueprint('social', __name__, url_prefix='/social')


# ============== Permission Decorators ==============

def check_banned(f):
    """Block all POST requests from banned users"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.is_banned:
            flash('Your account has been banned. You cannot perform this action.', 'error')
            return redirect(url_for('social.feed'))
        return f(*args, **kwargs)
    return decorated_function


def verified_required(f):
    """Require verified account for posting, commenting, etc."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_verified:
            flash('Please verify your email to access this feature.', 'warning')
            return redirect(url_for('auth.verify_otp'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Admin-only access"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('social.feed'))
        return f(*args, **kwargs)
    return decorated_function


# ============== Post List (Community Feed) ==============

@social_bp.route('/')
def feed():
    """Community feed - post list"""
    category = request.args.get('category', 'all')
    
    # Base query: exclude soft-deleted posts
    query = Post.query.filter_by(is_deleted=False)
    
    # Category filter
    if category != 'all':
        query = query.filter_by(category=category)
    
    # Pinned posts first, then by date descending
    posts = query.order_by(Post.is_pinned.desc(), Post.created_at.desc()).all()
    
    return render_template('social/feed.html', posts=posts, current_category=category)


# ============== Post Detail ==============

@social_bp.route('/post/<int:post_id>')
def post_detail(post_id):
    """Post detail page"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    # Increment view count
    post.view_count += 1
    db.session.commit()
    
    # Get non-deleted comments
    comments = post.comments.filter_by(is_deleted=False).order_by(Comment.created_at.asc()).all()
    
    # Check if current user liked/saved
    user_liked = False
    user_collected = False
    if current_user.is_authenticated:
        user_liked = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first() is not None
        user_collected = Collection.query.filter_by(user_id=current_user.id, post_id=post_id).first() is not None
    
    return render_template('social/post_detail.html', 
                           post=post, 
                           comments=comments,
                           user_liked=user_liked,
                           user_collected=user_collected)


# ============== Create Post ==============

@social_bp.route('/post', methods=['GET', 'POST'])
@verified_required
@check_banned
def create_post():
    """Create new post"""
    if request.method == 'GET':
        return render_template('social/create_post.html')
    
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    category = request.form.get('category', 'general')
    
    if not title or not body:
        flash('Title and content cannot be empty.', 'error')
        return redirect(url_for('social.create_post'))
    
    post = Post(
        title=title,
        body=body,
        category=category,
        author_id=current_user.id
    )
    db.session.add(post)
    db.session.commit()
    
    flash('Posted successfully!', 'success')
    return redirect(url_for('social.post_detail', post_id=post.id))


# ============== Edit Post ==============

@social_bp.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@verified_required
@check_banned
def edit_post(post_id):
    """Edit post - author or admin only"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    # Permission check
    if post.author_id != current_user.id and not current_user.is_admin():
        flash('You do not have permission to edit this post.', 'error')
        return redirect(url_for('social.post_detail', post_id=post_id))
    
    if request.method == 'GET':
        return render_template('social/edit_post.html', post=post)
    
    post.title = request.form.get('title', '').strip() or post.title
    post.body = request.form.get('body', '').strip() or post.body
    post.category = request.form.get('category', post.category)
    db.session.commit()
    
    flash('Updated successfully!', 'success')
    return redirect(url_for('social.post_detail', post_id=post_id))


# ============== Delete Post (Soft Delete) ==============

@social_bp.route('/post/<int:post_id>/delete', methods=['POST'])
@verified_required
@check_banned
def delete_post(post_id):
    """Soft delete post - author or admin only"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    # Permission check
    if post.author_id != current_user.id and not current_user.is_admin():
        flash('You do not have permission to delete this post.', 'error')
        return redirect(url_for('social.post_detail', post_id=post_id))
    
    # Soft delete
    post.is_deleted = True
    db.session.commit()
    
    flash('Post deleted.', 'success')
    return redirect(url_for('social.feed'))


# ============== Create Comment ==============

@social_bp.route('/post/<int:post_id>/comment', methods=['POST'])
@verified_required
@check_banned
def create_comment(post_id):
    """Create comment"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    body = request.form.get('body', '').strip()
    if not body:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('social.post_detail', post_id=post_id))
    
    comment = Comment(
        body=body,
        author_id=current_user.id,
        post_id=post_id
    )
    db.session.add(comment)
    db.session.commit()
    
    flash('Comment posted!', 'success')
    return redirect(url_for('social.post_detail', post_id=post_id))


# ============== Delete Comment (Soft Delete) ==============

@social_bp.route('/comment/<int:comment_id>/delete', methods=['POST'])
@verified_required
@check_banned
def delete_comment(comment_id):
    """Soft delete comment - author or admin only"""
    comment = Comment.query.filter_by(id=comment_id, is_deleted=False).first_or_404()
    
    # Permission check
    if comment.author_id != current_user.id and not current_user.is_admin():
        flash('You do not have permission to delete this comment.', 'error')
        return redirect(url_for('social.post_detail', post_id=comment.post_id))
    
    # Soft delete
    comment.is_deleted = True
    db.session.commit()
    
    flash('Comment deleted.', 'success')
    return redirect(url_for('social.post_detail', post_id=comment.post_id))


# ============== Like/Unlike ==============

@social_bp.route('/post/<int:post_id>/like', methods=['POST'])
@verified_required
@check_banned
def toggle_like(post_id):
    """Like or unlike post"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    existing_like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    
    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        message = 'Unliked'
    else:
        like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(like)
        db.session.commit()
        message = 'Liked!'
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': message, 'like_count': post.likes.count()})
    
    flash(message, 'success')
    return redirect(url_for('social.post_detail', post_id=post_id))


# ============== Save/Unsave ==============

@social_bp.route('/post/<int:post_id>/collect', methods=['POST'])
@verified_required
@check_banned
def toggle_collect(post_id):
    """Save or unsave post"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    existing_collection = Collection.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    
    if existing_collection:
        db.session.delete(existing_collection)
        db.session.commit()
        message = 'Unsaved'
    else:
        collection = Collection(user_id=current_user.id, post_id=post_id)
        db.session.add(collection)
        db.session.commit()
        message = 'Saved!'
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': message})
    
    flash(message, 'success')
    return redirect(url_for('social.post_detail', post_id=post_id))


# ============== Report Post ==============

@social_bp.route('/post/<int:post_id>/report', methods=['POST'])
@verified_required
@check_banned
def report_post(post_id):
    """Report post"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('Please enter a reason for reporting.', 'error')
        return redirect(url_for('social.post_detail', post_id=post_id))
    
    report = ContentReport(
        reporter_id=current_user.id,
        target_type='post',
        target_id=post_id,
        reason=reason
    )
    db.session.add(report)
    db.session.commit()
    
    flash('Report submitted. An admin will review it shortly.', 'success')
    return redirect(url_for('social.post_detail', post_id=post_id))


# ============== Admin: Pin/Unpin Post ==============

@social_bp.route('/post/<int:post_id>/pin', methods=['POST'])
@admin_required
def toggle_pin(post_id):
    """Pin/unpin post - admin only"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    post.is_pinned = not post.is_pinned
    db.session.commit()
    
    message = 'Post pinned' if post.is_pinned else 'Post unpinned'
    flash(message, 'success')
    return redirect(url_for('social.post_detail', post_id=post_id))


# ============== Admin: Ban/Unban User ==============

@social_bp.route('/user/<int:user_id>/ban', methods=['POST'])
@admin_required
def toggle_ban(user_id):
    """Ban/unban user - admin only"""
    user = User.query.get_or_404(user_id)
    
    if user.is_admin():
        flash('Cannot ban an admin account.', 'error')
        return redirect(url_for('social.feed'))
    
    user.is_banned = not user.is_banned
    db.session.commit()
    
    message = f'User {user.username} has been banned' if user.is_banned else f'User {user.username} has been unbanned'
    flash(message, 'success')
    return redirect(request.referrer or url_for('social.feed'))


# ============== Profile ==============

@social_bp.route('/profile')
@login_required
def profile():
    """Profile - my posts and saved items"""
    # My posts
    my_posts = Post.query.filter_by(author_id=current_user.id, is_deleted=False)\
                         .order_by(Post.created_at.desc()).all()
    
    # My saved posts
    my_collections = Collection.query.filter_by(user_id=current_user.id).all()
    collected_post_ids = [c.post_id for c in my_collections]
    collected_posts = Post.query.filter(Post.id.in_(collected_post_ids), Post.is_deleted==False).all() if collected_post_ids else []
    
    return render_template('social/profile.html', 
                           my_posts=my_posts,
                           collected_posts=collected_posts)


# ============== Admin: Report Management ==============

@social_bp.route('/admin/reports')
@admin_required
def admin_reports():
    """Admin report management dashboard"""
    reports = ContentReport.query.order_by(ContentReport.created_at.desc()).all()
    return render_template('social/admin_reports.html', reports=reports)


@social_bp.route('/admin/report/<int:report_id>/resolve', methods=['POST'])
@admin_required
def resolve_report(report_id):
    """Resolve report"""
    report = ContentReport.query.get_or_404(report_id)
    report.status = 'resolved'
    db.session.commit()
    
    flash('Report resolved.', 'success')
    return redirect(url_for('social.admin_reports'))


@social_bp.route('/admin/report/<int:report_id>/reject', methods=['POST'])
@admin_required
def reject_report(report_id):
    """Reject report"""
    report = ContentReport.query.get_or_404(report_id)
    report.status = 'rejected'
    db.session.commit()
    
    flash('Report rejected.', 'success')
    return redirect(url_for('social.admin_reports'))
