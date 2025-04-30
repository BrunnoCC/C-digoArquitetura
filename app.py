from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
import sqlite3
import os
import json
import shutil
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText

# Configurações
DB_PATH = 'database.db'
EXPORT_DB_PATH = 'exported_database.db'
EXPORT_JSON_PATH = 'exported_data.json'
EMAIL_SENDER = 'youremail@example.com'
EMAIL_PASSWORD = 'yourpassword'

app = Flask(__name__)
app.secret_key = 'secret-key'

# --- FUNÇÕES DE BANCO --- #

def connect_db():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Cria tabelas se não existirem."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                min_stock INTEGER NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                quantity_sold INTEGER NOT NULL,
                sale_date TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES inventory(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            )
        ''')
        conn.commit()

# --- INVENTÁRIO --- #

def add_product(name, quantity, min_stock):
    with connect_db() as conn:
        conn.execute('INSERT INTO inventory (name, quantity, min_stock) VALUES (?, ?, ?)',
                     (name, quantity, min_stock))
        conn.commit()


def get_inventory():
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT id, name, quantity, min_stock FROM inventory')
        return cur.fetchall()


def update_stock(product_id, quantity):
    with connect_db() as conn:
        conn.execute('UPDATE inventory SET quantity = ? WHERE id = ?',
                     (quantity, product_id))
        conn.commit()


def delete_product(product_id):
    with connect_db() as conn:
        conn.execute('DELETE FROM inventory WHERE id = ?', (product_id,))
        conn.commit()

# --- VENDAS --- #

def record_sale(product_id, quantity):
    sale_date = datetime.now().isoformat()
    with connect_db() as conn:
        conn.execute('INSERT INTO sales (product_id, quantity_sold, sale_date) VALUES (?, ?, ?)',
                     (product_id, quantity, sale_date))
        conn.execute('UPDATE inventory SET quantity = quantity - ? WHERE id = ?',
                     (quantity, product_id))
        conn.commit()


def get_sales_report(days=30):
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('''
            SELECT i.name, SUM(s.quantity_sold) AS total_sold
            FROM sales s
            JOIN inventory i ON s.product_id = i.id
            WHERE s.sale_date >= ?
            GROUP BY i.name
        ''', (since,))
        return cur.fetchall()

# --- ESTOQUE BAIXO --- #

def check_low_stock():
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT name, quantity, min_stock FROM inventory WHERE quantity < min_stock')
        return cur.fetchall()

# --- FORNECEDORES --- #

def add_supplier(name, email, phone):
    with connect_db() as conn:
        conn.execute('INSERT INTO suppliers (name, email, phone) VALUES (?, ?, ?)',
                     (name, email, phone))
        conn.commit()


def get_suppliers():
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT id, name, email, phone FROM suppliers')
        return cur.fetchall()

# --- MENSAGENS --- #

def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_SENDER
    msg['To'] = to_email
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)


def record_message(supplier_id, content):
    sent_at = datetime.now().isoformat()
    with connect_db() as conn:
        conn.execute('INSERT INTO messages (supplier_id, content, sent_at) VALUES (?, ?, ?)',
                     (supplier_id, content, sent_at))
        conn.commit()

# --- INÍCIO E INICIALIZAÇÃO --- #
init_db()

# --- ROTAS --- #

@app.route('/')
def index():
    inventory = get_inventory()
    alerts = check_low_stock()
    suppliers = get_suppliers()
    return render_template('index.html', inventory=inventory, alerts=alerts, suppliers=suppliers)

@app.route('/add', methods=['POST'])
def add():
    add_product(request.form['name'], int(request.form['quantity']), int(request.form['min_stock']))
    return redirect(url_for('index'))

@app.route('/update', methods=['POST'])
def update():
    update_stock(int(request.form['id']), int(request.form['quantity']))
    return redirect(url_for('index'))

@app.route('/delete', methods=['POST'])
def delete():
    delete_product(int(request.form['id']))
    return redirect(url_for('index'))

@app.route('/sell', methods=['POST'])
def sell():
    pid = int(request.form['id'])
    qty = int(request.form['quantity'])
    record_sale(pid, qty)
    return redirect(url_for('index'))

@app.route('/report')
def report():
    days = int(request.args.get('days', 30))
    sales_report = get_sales_report(days)
    return render_template('report.html', sales_report=sales_report, days=days)

@app.route('/recommend')
def recommend():
    # Obter inventário e gerar recomendações
    inventory = get_inventory()
    recommendations = []
    for _id, name, qty, min_stock in inventory:
        if qty < min_stock:
            needed = min_stock - qty
            recommendations.append((name, qty, min_stock, needed))
    return render_template('recommend.html', recommendations=recommendations)

@app.route('/supplier/add', methods=['POST'])
def supplier_add():
    add_supplier(request.form['sup_name'], request.form['sup_email'], request.form['sup_phone'])
    flash('Fornecedor adicionado com sucesso')
    return redirect(url_for('index'))

@app.route('/supplier/message', methods=['POST'])
def supplier_message():
    sup_id = int(request.form['sup_id'])
    content = request.form['message']
    sup = next(s for s in get_suppliers() if s[0] == sup_id)
    try:
        send_email(sup[2], 'Pedido de Reposição', content)
        record_message(sup_id, content)
        flash('Mensagem enviada com sucesso')
    except Exception as e:
        flash(f'Erro ao enviar: {e}')
    return redirect(url_for('index'))

@app.route('/export/db')
def export_db():
    shutil.copy(DB_PATH, EXPORT_DB_PATH)
    return send_file(EXPORT_DB_PATH, as_attachment=True)

@app.route('/export/json')
def export_json():
    data = [{'id':i[0],'name':i[1],'quantity':i[2],'min_stock':i[3]} for i in get_inventory()]
    with open(EXPORT_JSON_PATH,'w') as f:
        json.dump(data,f,indent=4)
    return send_file(EXPORT_JSON_PATH, as_attachment=True)

# Execução
if __name__ == '__main__':
    app.run(debug=True)
