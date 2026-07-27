import secrets
import os
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
THUMB_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'thumbnails')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMB_FOLDER, exist_ok=True)

ALLOWED_IMG = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['THUMB_FOLDER'] = THUMB_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)


# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar_color = db.Column(db.String(7), default='#6C5CE7')
    role = db.Column(db.String(20), default='membro')
    badge = db.Column(db.String(50), default='none')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def display_badge(self):
        if self.badge == 'beta':
            return 'beta'
        if self.id <= 100:
            return 'beta'
        return 'none'


class Channel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    messages = db.relationship('Message', backref='channel', lazy=True)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    user = db.relationship('User', backref='messages')


class Download(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    category = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    original_filename = db.Column(db.String(300), nullable=False)
    version = db.Column(db.String(20), default='1.0')
    thumbnail = db.Column(db.String(300), default='')   # nome do arquivo de imagem
    downloads_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    uploader = db.relationship('User', backref='uploads')


class OptimizationTip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False)          # ordem de exibição
    icon = db.Column(db.String(10), default='🔧')
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    bullets = db.Column(db.Text, default='')                # itens separados por \n
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('Acesso negado.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMG


# --- Auth Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Usuário ou senha inválidos.', 'error')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash('Nome de usuário já existe.', 'error')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('Email já registrado.', 'error')
            return render_template('register.html')

        user_count = User.query.count()
        colors = ['#6C5CE7', '#00CEC9', '#FD79A8', '#FDCB6E', '#E17055', '#00B894']
        badge = 'beta' if user_count < 100 else 'none'
        user = User(username=username, email=email, avatar_color=secrets.choice(colors), badge=badge)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        msg = 'Conta criada!'
        if badge == 'beta':
            msg += ' Badge Beta conquistado! 🎖️'
        flash(msg, 'success')
        return redirect(url_for('index'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# --- Public Routes ---
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/aplicativos')
def aplicativos():
    apps = Download.query.filter_by(category='aplicativos').order_by(Download.created_at.desc()).all()
    return render_template('aplicativos.html', downloads=apps)


@app.route('/otimizacao')
def otimizacao():
    tips = OptimizationTip.query.order_by(OptimizationTip.number.asc()).all()
    return render_template('otimizacao.html', tips=tips)


@app.route('/arquivos')
def arquivos():
    files = Download.query.filter_by(category='arquivos').order_by(Download.created_at.desc()).all()
    return render_template('arquivos.html', downloads=files)


@app.route('/download/<int:id>')
def download_file(id):
    dl = Download.query.get_or_404(id)
    dl.downloads_count += 1
    db.session.commit()
    return send_from_directory(app.config['UPLOAD_FOLDER'], dl.filename, as_attachment=True, download_name=dl.original_filename)


@app.route('/thumbnail/<filename>')
def serve_thumbnail(filename):
    return send_from_directory(app.config['THUMB_FOLDER'], filename)


# --- Admin Routes ---
@app.route('/admin')
@admin_required
def admin_panel():
    users = User.query.all()
    downloads = Download.query.order_by(Download.created_at.desc()).all()
    tips = OptimizationTip.query.order_by(OptimizationTip.number.asc()).all()
    return render_template('admin.html', users=users, downloads=downloads, tips=tips)


@app.route('/admin/upload', methods=['POST'])
@admin_required
def admin_upload():
    if 'file' not in request.files:
        flash('Nenhum arquivo selecionado.', 'error')
        return redirect(url_for('admin_panel'))

    file = request.files['file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado.', 'error')
        return redirect(url_for('admin_panel'))

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', 'arquivos')
    version = request.form.get('version', '1.0').strip()

    if not title:
        flash('Título é obrigatório.', 'error')
        return redirect(url_for('admin_panel'))

    filename = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    # Thumbnail opcional
    thumb_name = ''
    thumb_file = request.files.get('thumbnail')
    if thumb_file and thumb_file.filename and allowed_image(thumb_file.filename):
        thumb_name = secure_filename(f"thumb_{secrets.token_hex(6)}_{thumb_file.filename}")
        thumb_file.save(os.path.join(app.config['THUMB_FOLDER'], thumb_name))

    dl = Download(
        title=title,
        description=description,
        category=category,
        filename=filename,
        original_filename=file.filename,
        version=version,
        thumbnail=thumb_name,
        uploader_id=current_user.id
    )
    db.session.add(dl)
    db.session.commit()

    flash(f'"{title}" enviado com sucesso!', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/edit-download/<int:id>', methods=['POST'])
@admin_required
def admin_edit_download(id):
    dl = Download.query.get_or_404(id)
    dl.title = request.form.get('title', dl.title).strip()
    dl.description = request.form.get('description', dl.description).strip()
    dl.version = request.form.get('version', dl.version).strip()
    dl.category = request.form.get('category', dl.category)

    # Nova thumbnail opcional
    thumb_file = request.files.get('thumbnail')
    if thumb_file and thumb_file.filename and allowed_image(thumb_file.filename):
        # Deleta thumbnail antiga
        if dl.thumbnail:
            old = os.path.join(app.config['THUMB_FOLDER'], dl.thumbnail)
            if os.path.exists(old):
                os.remove(old)
        thumb_name = secure_filename(f"thumb_{secrets.token_hex(6)}_{thumb_file.filename}")
        thumb_file.save(os.path.join(app.config['THUMB_FOLDER'], thumb_name))
        dl.thumbnail = thumb_name

    db.session.commit()
    flash(f'"{dl.title}" atualizado!', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/delete-download/<int:id>')
@admin_required
def admin_delete_download(id):
    dl = Download.query.get_or_404(id)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], dl.filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    if dl.thumbnail:
        tp = os.path.join(app.config['THUMB_FOLDER'], dl.thumbnail)
        if os.path.exists(tp):
            os.remove(tp)
    db.session.delete(dl)
    db.session.commit()
    flash(f'"{dl.title}" removido.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/set-role/<int:user_id>/<role>')
@admin_required
def admin_set_role(user_id, role):
    if role not in ('admin', 'membro'):
        flash('Cargo inválido.', 'error')
        return redirect(url_for('admin_panel'))
    user = User.query.get_or_404(user_id)
    user.role = role
    db.session.commit()
    flash(f'Cargo de {user.username} → {role}.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/set-badge/<int:user_id>/<badge>')
@admin_required
def admin_set_badge(user_id, badge):
    if badge not in ('beta', 'none'):
        flash('Insígnia inválida.', 'error')
        return redirect(url_for('admin_panel'))
    user = User.query.get_or_404(user_id)
    user.badge = badge
    db.session.commit()
    flash(f'Insígnia de {user.username} alterada.', 'success')
    return redirect(url_for('admin_panel'))


# --- Admin: Dicas de Otimização ---
@app.route('/admin/tip/add', methods=['POST'])
@admin_required
def admin_add_tip():
    number = request.form.get('number', '1')
    icon = request.form.get('icon', '🔧').strip() or '🔧'
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    bullets_raw = request.form.get('bullets', '').strip()

    if not title or not description:
        flash('Título e descrição são obrigatórios.', 'error')
        return redirect(url_for('admin_panel'))

    try:
        number = int(number)
    except ValueError:
        number = OptimizationTip.query.count() + 1

    tip = OptimizationTip(
        number=number,
        icon=icon,
        title=title,
        description=description,
        bullets=bullets_raw
    )
    db.session.add(tip)
    db.session.commit()
    flash(f'Dica "{title}" adicionada!', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/tip/edit/<int:tip_id>', methods=['POST'])
@admin_required
def admin_edit_tip(tip_id):
    tip = OptimizationTip.query.get_or_404(tip_id)
    tip.number = int(request.form.get('number', tip.number))
    tip.icon = request.form.get('icon', tip.icon).strip() or tip.icon
    tip.title = request.form.get('title', tip.title).strip()
    tip.description = request.form.get('description', tip.description).strip()
    tip.bullets = request.form.get('bullets', tip.bullets).strip()
    db.session.commit()
    flash(f'Dica "{tip.title}" atualizada!', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/tip/delete/<int:tip_id>')
@admin_required
def admin_delete_tip(tip_id):
    tip = OptimizationTip.query.get_or_404(tip_id)
    db.session.delete(tip)
    db.session.commit()
    flash('Dica removida.', 'success')
    return redirect(url_for('admin_panel'))


# --- Chat Routes ---
@app.route('/chat')
@login_required
def chat():
    channels = Channel.query.all()
    if not channels:
        default = Channel(name='geral', description='Bate-papo geral da comunidade')
        db.session.add(default)
        db.session.commit()
        channels = Channel.query.all()
    return render_template('chat.html', channels=channels, role=current_user.role, badge=current_user.display_badge)


@app.route('/api/channels', methods=['POST'])
@login_required
def create_channel():
    data = request.get_json()
    name = data.get('name', '').strip().lower()
    desc = data.get('description', '')
    if not name:
        return jsonify({'error': 'Nome é obrigatório.'}), 400
    if Channel.query.filter_by(name=name).first():
        return jsonify({'error': 'Canal já existe.'}), 400
    ch = Channel(name=name, description=desc)
    db.session.add(ch)
    db.session.commit()
    return jsonify({'id': ch.id, 'name': ch.name, 'description': ch.description})


@app.route('/api/messages/<int:channel_id>')
@login_required
def get_messages(channel_id):
    msgs = Message.query.filter_by(channel_id=channel_id)\
        .order_by(Message.timestamp.desc()).limit(100).all()
    msgs.reverse()
    return jsonify([{
        'id': m.id,
        'content': m.content,
        'timestamp': m.timestamp.strftime('%d/%m/%Y %H:%M'),
        'user': m.user.username,
        'avatar_color': m.user.avatar_color,
        'user_id': m.user.id,
        'role': m.user.role,
        'badge': m.user.display_badge
    } for m in msgs])


@app.route('/api/user-info')
@login_required
def api_user_info():
    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'avatar_color': current_user.avatar_color,
        'role': current_user.role,
        'badge': current_user.display_badge
    })


# --- SocketIO Events ---
online_users = {}

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        online_users[current_user.id] = {
            'username': current_user.username,
            'avatar_color': current_user.avatar_color,
            'role': current_user.role,
            'badge': current_user.display_badge
        }
        emit('user_list', list(online_users.values()), broadcast=True)


@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        online_users.pop(current_user.id, None)
        emit('user_list', list(online_users.values()), broadcast=True)


@socketio.on('join_channel')
def handle_join(data):
    join_room(f'channel_{data["channel_id"]}')


@socketio.on('leave_channel')
def handle_leave(data):
    leave_room(f'channel_{data["channel_id"]}')


@socketio.on('send_message')
def handle_message(data):
    channel_id = data['channel_id']
    content = data['content'].strip()
    if not content:
        return

    msg = Message(content=content, user_id=current_user.id, channel_id=channel_id)
    db.session.add(msg)
    db.session.commit()

    emit('new_message', {
        'id': msg.id,
        'content': msg.content,
        'timestamp': msg.timestamp.strftime('%d/%m/%Y %H:%M'),
        'user': current_user.username,
        'avatar_color': current_user.avatar_color,
        'user_id': current_user.id,
        'role': current_user.role,
        'badge': current_user.display_badge
    }, room=f'channel_{channel_id}')


@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {
        'username': current_user.username,
        'channel_id': data['channel_id']
    }, room=f'channel_{data["channel_id"]}', include_self=False)


@socketio.on('stop_typing')
def handle_stop_typing(data):
    emit('user_stop_typing', {
        'username': current_user.username,
        'channel_id': data['channel_id']
    }, room=f'channel_{data["channel_id"]}', include_self=False)


DEFAULT_TIPS = [
    (1, '🧹', 'Limpeza de Cache', 'O cache acumulado consome espaço e pode deixar o app lento. Limpe regularmente os arquivos temporários.',
     'Use ferramentas de limpeza automática\nLimpe o cache a cada 2-3 dias\nEvite limpar dados importantes (senhas, login)'),
    (2, '⚡', 'Gerenciamento de RAM', 'Apps em segundo plano consomem memória. Feche processos desnecessários para liberar RAM.',
     'Force feche apps que não está usando\nUse modos de economia de bateria\nDesative auto-sincronização desnecessária'),
    (3, '📱', 'Atualize Sempre', 'Atualizações trazem correções de bugs e otimizações de performance. Mantenha tudo atualizado.',
     'Ative atualizações automáticas\nVerifique notas de versão\nAtualize o sistema operacional também'),
    (4, '🔋', 'Economia de Bateria', 'Ajuste brilho, desative GPS/Bluetooth quando não usar e ative o modo de economia.',
     'Reduza o brilho da tela\nDesative localização para apps que não precisam\nUse Wi-Fi ao invés de dados móveis quando possível'),
    (5, '🗂️', 'Organize seus Apps', 'Desinstale apps que não usa. Apps desnecessários ocupam espaço e rodam em background.',
     'Revise seus apps mensalmente\nUse versões Lite quando disponível\nDesative notificações excessivas'),
    (6, '🔧', 'Use Ferramentas Certas', 'Nossa plataforma oferece ferramentas de otimização que automatizam muitos desses processos.',
     'Baixe nossas ferramentas na aba Downloads\nScripts de automação disponíveis\nConfigurações otimizadas prontas'),
]

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        # Migration automática — adiciona colunas novas se não existirem
        with db.engine.connect() as conn:
            existing = [row[1] for row in conn.execute(db.text("PRAGMA table_info(download)")).fetchall()]
            if 'thumbnail' not in existing:
                conn.execute(db.text('ALTER TABLE download ADD COLUMN thumbnail VARCHAR(300) DEFAULT ""'))
                conn.commit()
                print("✅ Migration: coluna 'thumbnail' adicionada")
            if 'version' not in existing:
                conn.execute(db.text('ALTER TABLE download ADD COLUMN version VARCHAR(20) DEFAULT "1.0"'))
                conn.commit()
                print("✅ Migration: coluna 'version' adicionada")
        if not User.query.filter_by(role='admin').first():
            admin = User(username='admin', email='admin@volker.app', role='admin', badge='beta', avatar_color='#E17055')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        # Seed dicas padrão se não existirem
        if OptimizationTip.query.count() == 0:
            for num, icon, title, desc, bullets in DEFAULT_TIPS:
                db.session.add(OptimizationTip(number=num, icon=icon, title=title, description=desc, bullets=bullets))
            db.session.commit()
    socketio.run(app, host='0.0.0.0', port=80, debug=True)
