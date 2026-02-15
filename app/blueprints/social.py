from functools import wraps
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, abort, current_app
import base64
from flask_login import login_required, current_user
from app.models.content import Post, Comment
from app.models.interaction import Like, Collection, CommentLike
from app.models.content_report import ContentReport
from app.models.private_message import PrivateMessage
from app.models.user import User
from app.extensions import db
from sqlalchemy import or_, and_, func
from sqlalchemy.exc import IntegrityError

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
    """Community feed - post list with pagination"""
    category = request.args.get('category', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # 每页显示20个帖子
    
    # Base query: exclude soft-deleted posts
    query = Post.query.filter_by(is_deleted=False)
    
    # Category filter
    if category != 'all':
        query = query.filter_by(category=category)
    
    # Pinned posts first, then by date descending, with pagination
    pagination = query.order_by(Post.is_pinned.desc(), Post.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    posts = pagination.items
    
    return render_template('social/feed.html', 
                           posts=posts, 
                           current_category=category,
                           pagination=pagination)


# ============== Post Detail ==============

@social_bp.route('/post/<int:post_id>')
def post_detail(post_id):
    """Post detail page"""
    post = Post.query.filter_by(id=post_id, is_deleted=False).first_or_404()
    
    # Atomic increment avoids lost updates under concurrent requests.
    Post.query.filter_by(id=post_id, is_deleted=False).update(
        {Post.view_count: Post.view_count + 1}
    )
    db.session.commit()
    db.session.refresh(post)
    
    # Get non-deleted comments
    comments = post.comments.filter_by(is_deleted=False).order_by(Comment.created_at.asc()).all()
    
    # Check if current user liked/saved post
    user_liked = False
    user_collected = False
    liked_comment_ids = set()
    comment_like_counts = {}
    
    # Get comment IDs for this post
    comment_ids = [c.id for c in comments]
    
    # Get comment like counts
    if comment_ids:
        counts = db.session.query(
            CommentLike.comment_id,
            func.count(CommentLike.id)
        ).filter(
            CommentLike.comment_id.in_(comment_ids)
        ).group_by(
            CommentLike.comment_id
        ).all()
        comment_like_counts = {comment_id: count for comment_id, count in counts}
    
    if current_user.is_authenticated:
        user_liked = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first() is not None
        user_collected = Collection.query.filter_by(user_id=current_user.id, post_id=post_id).first() is not None
        
        # Get comment IDs that user liked
        if comment_ids:
            user_comment_likes = CommentLike.query.filter(
                CommentLike.user_id == current_user.id,
                CommentLike.comment_id.in_(comment_ids)
            ).all()
            liked_comment_ids = {cl.comment_id for cl in user_comment_likes}
    
    return render_template('social/post_detail.html', 
                           post=post, 
                           comments=comments,
                           user_liked=user_liked,
                           user_collected=user_collected,
                           liked_comment_ids=liked_comment_ids,
                           comment_like_counts=comment_like_counts)


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
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
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
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
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

@social_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit profile (nickname, avatar)"""
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        avatar_file = request.files.get('avatar')
        
        # Update nickname
        if nickname:
            current_user.nickname = nickname
            
        # Handle Avatar Upload
        if avatar_file and avatar_file.filename:
            mimetype = avatar_file.mimetype
            if mimetype not in ['image/jpeg', 'image/png']:
                flash('Invalid image format. Only JPEG and PNG are allowed.', 'error')
                return redirect(url_for('social.edit_profile'))

            max_avatar_size = int(current_app.config.get('MAX_CONTENT_LENGTH') or (2 * 1024 * 1024))
            avatar_data = avatar_file.read(max_avatar_size + 1)
            if len(avatar_data) > max_avatar_size:
                flash('Image is too large. Please upload a file smaller than 2MB.', 'error')
                return redirect(url_for('social.edit_profile'))

            current_user.avatar = avatar_data
            current_user.avatar_mimetype = mimetype
            
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('social.profile'))
        
    return render_template('social/profile_edit.html')

@social_bp.app_template_filter('b64encode')
def b64encode_filter(data):
    if not data:
        return ''
    return base64.b64encode(data).decode('utf-8')


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


# ============== Reply to Comment (Nested Comments) ==============

@social_bp.route('/comment/<int:comment_id>/reply', methods=['POST'])
@verified_required
@check_banned
def reply_comment(comment_id):
    """Reply to a comment (nested comment)"""
    parent_comment = Comment.query.filter_by(id=comment_id, is_deleted=False).first_or_404()
    
    body = request.form.get('body', '').strip()
    if not body:
        flash('Reply cannot be empty.', 'error')
        return redirect(url_for('social.post_detail', post_id=parent_comment.post_id))
    
    # 找到顶级评论 (如果 parent 本身是子评论，则指向其 parent)
    top_parent_id = parent_comment.parent_id if parent_comment.parent_id else parent_comment.id
    reply_to_user_id = parent_comment.author_id
    
    reply = Comment(
        body=body,
        author_id=current_user.id,
        post_id=parent_comment.post_id,
        parent_id=top_parent_id,
        reply_to_user_id=reply_to_user_id
    )
    db.session.add(reply)
    db.session.commit()
    
    flash('Reply posted!', 'success')
    return redirect(url_for('social.post_detail', post_id=parent_comment.post_id))


# ============== Private Messages ==============

@social_bp.route('/messages/')
@verified_required
def messages_list():
    """List all conversations"""
    all_messages = PrivateMessage.query.filter(
        or_(
            PrivateMessage.sender_id == current_user.id,
            PrivateMessage.receiver_id == current_user.id
        )
    ).order_by(PrivateMessage.created_at.desc()).all()

    other_user_ids = {
        (msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id)
        for msg in all_messages
    }
    user_map = {}
    unread_count_map = {}
    if other_user_ids:
        users = User.query.filter(User.id.in_(other_user_ids)).all()
        user_map = {user.id: user for user in users}
        unread_rows = db.session.query(
            PrivateMessage.sender_id,
            func.count(PrivateMessage.id)
        ).filter(
            PrivateMessage.receiver_id == current_user.id,
            PrivateMessage.is_read.is_(False),
            PrivateMessage.sender_id.in_(other_user_ids)
        ).group_by(
            PrivateMessage.sender_id
        ).all()
        unread_count_map = {sender_id: count for sender_id, count in unread_rows}

    conversations = {}
    for msg in all_messages:
        other_user_id = msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
        if other_user_id not in conversations and other_user_id in user_map:
            conversations[other_user_id] = {
                'user': user_map[other_user_id],
                'last_message': msg,
                'unread_count': unread_count_map.get(other_user_id, 0),
            }

    sorted_conversations = sorted(
        conversations.values(),
        key=lambda x: x['last_message'].created_at,
        reverse=True
    )
    
    return render_template('social/messages.html', conversations=sorted_conversations)


@social_bp.route('/messages/<int:user_id>', methods=['GET', 'POST'])
@verified_required
@check_banned
def chat(user_id):
    """Chat with a specific user"""
    other_user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        body = request.form.get('body', '').strip()
        if body:
            message = PrivateMessage(
                sender_id=current_user.id,
                receiver_id=user_id,
                body=body
            )
            db.session.add(message)
            db.session.commit()
        return redirect(url_for('social.chat', user_id=user_id))
    
    # 获取两人之间的所有消息
    messages = PrivateMessage.query.filter(
        or_(
            and_(PrivateMessage.sender_id == current_user.id, PrivateMessage.receiver_id == user_id),
            and_(PrivateMessage.sender_id == user_id, PrivateMessage.receiver_id == current_user.id)
        )
    ).order_by(PrivateMessage.created_at.asc()).all()
    
    # 标记对方发来的消息为已读
    PrivateMessage.query.filter_by(
        sender_id=user_id,
        receiver_id=current_user.id,
        is_read=False
    ).update({'is_read': True})
    db.session.commit()
    
    return render_template('social/chat.html', other_user=other_user, messages=messages)


@social_bp.route('/messages/unread_count')
@login_required
def unread_count():
    """Get total unread message count (for AJAX)"""
    if not current_user.is_verified:
        return jsonify({'count': 0})
    
    count = PrivateMessage.query.filter_by(
        receiver_id=current_user.id,
        is_read=False
    ).count()
    return jsonify({'count': count})


# ============== Comment Interactions ==============

@social_bp.route('/comment/<int:comment_id>/like', methods=['POST'])
@verified_required
@check_banned
def toggle_comment_like(comment_id):
    """Toggle like on a comment"""
    comment = Comment.query.get_or_404(comment_id)
    if comment.is_deleted:
        abort(404)
    
    existing = CommentLike.query.filter_by(
        user_id=current_user.id,
        comment_id=comment_id
    ).first()
    
    if existing:
        db.session.delete(existing)
        flash('取消点赞', 'info')
    else:
        like = CommentLike(user_id=current_user.id, comment_id=comment_id)
        db.session.add(like)
        flash('Liked', 'success')

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return redirect(url_for('social.post_detail', post_id=comment.post_id))


@social_bp.route('/comment/<int:comment_id>/report', methods=['POST'])
@login_required
@verified_required
@check_banned
def report_comment(comment_id):
    """Report a comment"""
    comment = Comment.query.get_or_404(comment_id)
    if comment.is_deleted:
        abort(404)
    
    if comment.author_id == current_user.id:
        flash('You cannot report your own comment.', 'warning')
        return redirect(url_for('social.post_detail', post_id=comment.post_id))
    
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('Please provide a reason for reporting.', 'warning')
        return redirect(url_for('social.post_detail', post_id=comment.post_id))
    
    # Check if already reported
    existing = ContentReport.query.filter_by(
        reporter_id=current_user.id,
        target_type='comment',
        target_id=comment_id
    ).first()
    
    if existing:
        flash('You have already reported this comment.', 'info')
        return redirect(url_for('social.post_detail', post_id=comment.post_id))
    
    report = ContentReport(
        reporter_id=current_user.id,
        target_type='comment',
        target_id=comment_id,
        reason=reason
    )
    db.session.add(report)
    db.session.commit()
    
    flash('Comment reported. Thank you for helping keep our community safe.', 'success')
    return redirect(url_for('social.post_detail', post_id=comment.post_id))


