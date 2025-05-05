from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import hashlib

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mysecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['POST_UPLOAD_FOLDER'] = 'static/uploads/posts'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    avatar = db.Column(db.String(120), nullable=False, default='default.jpg')
    posts = db.relationship('Post', backref='author', lazy=True)
    comments = db.relationship('Comment', backref='author', lazy=True)
    likes = db.relationship('Like', backref='user', lazy=True)

    def get_gravatar_url(self, size=100):
        email_hash = hashlib.md5(self.email.lower().encode('utf-8')).hexdigest()
        return f"https://www.gravatar.com/avatar/{email_hash}?d=identicon&s={size}"

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(120))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comments = db.relationship('Comment', backref='post', lazy='joined')
    likes = db.relationship('Like', backref='post', lazy=True)

    @property
    def root_comments(self):
        return [comment for comment in self.comments if comment.parent_id is None]

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy='joined')

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    is_private = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.drop_all()
    db.create_all()
    print("База данных создана")

@app.route('/')
def index():
    posts = Post.query.options(
        db.joinedload(Post.author),
        db.joinedload(Post.comments).joinedload(Comment.author)
    ).all()
    return render_template('index.html', posts=posts)

@app.route('/like', methods=['POST'])
@login_required
def handle_like():
    post_id = request.form.get('post_id')
    post = Post.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()

    if like:
        db.session.delete(like)
    else:
        new_like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(new_like)

    db.session.commit()
    return redirect(request.referrer)

@app.route('/toggle_privacy', methods=['POST'])
@login_required
def toggle_privacy():
    like_id = request.form.get('like_id')

    if not like_id:
        flash('Ошибка: лайк не найден', 'danger')
        return redirect(url_for('index'))

    like = Like.query.get(like_id)

    if not like or like.user_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('index'))

    like.is_private = not like.is_private
    db.session.commit()
    return redirect(request.referrer)

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    content = request.form.get('content')
    parent_id = request.form.get('parent_id')

    if not content:
        flash('Комментарий не может быть пустым', 'danger')
        return redirect(url_for('index'))

    try:
        parent_id = int(parent_id) if parent_id else None
        new_comment = Comment(
            content=content,
            post_id=post.id,
            user_id=current_user.id,
            parent_id=parent_id
        )
        db.session.add(new_comment)
        db.session.commit()
        flash('Комментарий добавлен!', 'success')
    except Exception as e:
        print(f"Ошибка: {e}")
        flash('Ошибка при добавлении комментария', 'danger')

    return redirect(url_for('index') + f'#post-{post.id}')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        if User.query.filter_by(username=username).first():
            flash('Пользователь уже существует!', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email уже зарегистрирован!', 'danger')
            return redirect(url_for('register'))
        new_user = User(username=username, password=password, email=email)
        db.session.add(new_user)
        db.session.commit()
        flash('Регистрация прошла успешно! Войдите.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('index'))
        flash('Неверный логин или пароль!', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/create_post', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        image = None

        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(app.config['POST_UPLOAD_FOLDER'], exist_ok=True)
                file.save(os.path.join(app.config['POST_UPLOAD_FOLDER'], filename))
                image = filename

        new_post = Post(
            title=title,
            content=content,
            image=image,
            user_id=current_user.id
        )
        db.session.add(new_post)
        db.session.commit()
        flash('Пост создан!', 'success')
        return redirect(url_for('index'))

    return render_template('create_post.html')

@app.route('/user/<username>')
def user_page(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).options(
        db.joinedload(Post.comments).joinedload(Comment.author)
    ).all()
    comments = Comment.query.filter_by(user_id=user.id).options(
        db.joinedload(Comment.post),
        db.joinedload(Comment.author)
    ).all()

    likes_query = Like.query.filter_by(user_id=user.id)
    if current_user != user:
        likes_query = likes_query.filter_by(is_private=False)

    liked_posts = [like.post for like in likes_query.join(Post).all()]

    return render_template('user_page.html',
                           user=user,
                           posts=posts,
                           comments=comments,
                           liked_posts=liked_posts)

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        if username != current_user.username and User.query.filter_by(username=username).first():
            flash('Этот никнейм уже занят!', 'danger')
            return redirect(url_for('edit_profile'))
        if email != current_user.email and User.query.filter_by(email=email).first():
            flash('Этот email уже зарегистрирован!', 'danger')
            return redirect(url_for('edit_profile'))

        current_user.username = username
        current_user.email = email

        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                current_user.avatar = filename

        db.session.commit()
        flash('Профиль обновлён!', 'success')
        return redirect(url_for('user_page', username=current_user.username))

    return render_template('edit_profile.html')

if __name__ == '__main__':
    app.run(debug=True)