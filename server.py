"""
BioKB 数据采集与后端服务
功能：
  1. 从多个数据源自动采集生物医药领域最新内容
  2. 使用 AI 对内容进行相关性评分和摘要
  3. 提供 REST API 供前端调用
  4. 生成周报/月报
"""

import sqlite3
import json
import hashlib
import threading
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import feedparser
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'feedparser', '-q'])
    import feedparser

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests', '-q'])
    import requests

# ==================== 配置 ====================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
REPORTS_DIR = BASE_DIR / 'reports'
DB_PATH = DATA_DIR / 'biokb.db'
API_BASE = 'https://academicapi.com/v1'
API_KEY = 'sk-nzR1BI7nFGj42BCx6LJS4Pl5U4fYZuGyLNNf32PtnOs50Z10'

# 数据源 RSS 配置
RSS_SOURCES = {
    'PubMed创新药': {
        'url': 'https://pubmed.ncbi.nlm.nih.gov/rss/search/123/?limit=20&utm_campaign=pubmed-2&fc=20250101',
        'category': 'innovation',
        'query': 'novel drug therapy OR innovative drug OR breakthrough therapy OR new molecular entity'
    },
    'PubMed生物制造': {
        'url': 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=(biomanufacturing+OR+synthetic+biology+OR+bioprocessing)&retmax=20&sort=date&rettype=rss',
        'category': 'biomanufacturing',
    },
    'Nature头条': {
        'url': 'https://www.nature.com/nature.rss',
        'category': 'innovation',
    },
    'Nature生物技术': {
        'url': 'https://www.nature.com/nbt.rss',
        'category': 'biomanufacturing',
    },
    'bioRxiv最新': {
        'url': 'http://connect.biorxiv.org/biorxiv_xml.php?subject=molecular_biology',
        'category': 'innovation',
    },
    'FDA新闻': {
        'url': 'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/fda-news-releases/rss.xml',
        'category': 'innovation',
    },
    '药智网': {
        'url': None,  # 爬虫采集
        'category': 'innovation',
    },
}

# AI 评分 prompt
RELEVANCE_PROMPT = """你是一个生物医药领域的专家评审。请评估以下文章与以下领域的相关性：
- 创新药（novel drugs, CAR-T, gene therapy, antibody drug conjugate, mRNA therapy等）
- 生物制造（biomanufacturing, synthetic biology, bioprocessing, CDMO等）
- 大健康（healthcare, precision medicine, aging, public health等）

文章标题：{title}
文章摘要：{summary}

请以JSON格式回复：
{{"category": "innovation/biomanufacturing/health/scholar", "relevance_score": 1-10, "tags": ["标签1","标签2"], "chinese_summary": "中文摘要（50-100字）"}}

只返回JSON，不要其他内容。"""


# ==================== 数据库 ====================
def init_db():
    """初始化 SQLite 数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        summary TEXT,
        chinese_summary TEXT,
        url TEXT UNIQUE,
        source TEXT,
        category TEXT,
        journal TEXT,
        authors TEXT,
        publish_date TEXT,
        tags TEXT,
        ai_score INTEGER,
        content_hash TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_category ON articles(category)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_source ON articles(source)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_date ON articles(publish_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_hash ON articles(content_hash)')
    c.execute('''CREATE TABLE IF NOT EXISTS scholars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        organization TEXT,
        field TEXT,
        google_scholar_id TEXT,
        track_since TEXT,
        last_check TEXT,
        notes TEXT,
        resume TEXT,
        resume_updated_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        period TEXT,
        content TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS phage_trials_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nct_id TEXT NOT NULL,
        title TEXT,
        status TEXT,
        phases TEXT,
        last_status TEXT,
        last_update TEXT,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()
    print(f"[DB] 数据库已初始化: {DB_PATH}")


def migrate_db():
    """数据库迁移：添加新字段"""
    conn = get_connection()
    c = conn.cursor()
    # Check and add resume column
    c.execute("PRAGMA table_info(scholars)")
    cols = [row[1] for row in c.fetchall()]
    if 'resume' not in cols:
        c.execute('ALTER TABLE scholars ADD COLUMN resume TEXT')
        print("[DB] 迁移: 添加 scholars.resume 字段")
    if 'resume_updated_at' not in cols:
        c.execute('ALTER TABLE scholars ADD COLUMN resume_updated_at TEXT')
        print("[DB] 迁移: 添加 scholars.resume_updated_at 字段")
    conn.commit()
    conn.close()


def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


# ==================== 内容哈希 ====================
def make_hash(title, source):
    return hashlib.md5(f"{title}|{source}".encode()).hexdigest()


# ==================== RSS 采集 ====================
def fetch_rss(source_name, config):
    """从 RSS 源采集文章"""
    url = config.get('url')
    if not url:
        return []

    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            title = entry.get('title', '').strip()
            if not title:
                continue
            summary = ''
            if hasattr(entry, 'summary'):
                summary = entry.summary
            elif hasattr(entry, 'description'):
                summary = entry.description
            # Clean HTML
            import re
            summary = re.sub(r'<[^>]+>', '', summary).strip()[:500]

            url_link = entry.get('link', '')
            authors = []
            if hasattr(entry, 'authors'):
                authors = [a.get('name', '') for a in entry.authors]
            elif hasattr(entry, 'author_detail'):
                authors = [entry.author_detail.get('name', '')]
            elif hasattr(entry, 'author'):
                authors = [entry.author]

            date = ''
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                except:
                    pass
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    date = datetime(*entry.updated_parsed[:6]).strftime('%Y-%m-%d')
                except:
                    pass

            articles.append({
                'title': title,
                'summary': summary,
                'url': url_link,
                'source': source_name,
                'category': config.get('category', 'innovation'),
                'authors': authors,
                'date': date,
                'journal': source_name,
            })
        print(f"[RSS] {source_name}: 采集 {len(articles)} 篇")
    except Exception as e:
        print(f"[RSS] {source_name} 采集失败: {e}")
    return articles


# ==================== Web 爬虫 ====================
def fetch_yaozh_news():
    """爬取药智网最新医药新闻"""
    articles = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get('https://news.yaozh.com/', headers=headers, timeout=15)
        if resp.status_code == 200:
            import re
            # Extract article links and titles
            links = re.findall(r'<a[^>]+href="(/archives/\d+)"[^>]*>([^<]+)</a>', resp.text)
            for link, title in links[:15]:
                title = title.strip()
                if len(title) > 10:
                    articles.append({
                        'title': title,
                        'summary': '',
                        'url': f'https://news.yaozh.com{link}',
                        'source': '药智网',
                        'category': 'innovation',
                        'authors': [],
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'journal': '药智新闻',
                    })
            print(f"[爬虫] 药智网: 采集 {len(articles)} 篇")
    except Exception as e:
        print(f"[爬虫] 药智网采集失败: {e}")
    return articles


def fetch_arxiv_bio():
    """从 arXiv 采集最新生物医药论文"""
    articles = []
    try:
        url = 'http://export.arxiv.org/api/query?search_query=cat:q-bio*&sortBy=submittedDate&sortOrder=descending&max_results=15'
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.get('title', '').strip().replace('\n', ' ')
            summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:500] if hasattr(entry, 'summary') else ''
            authors = [a.get('name', '') for a in getattr(entry, 'authors', [])]
            date = ''
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                except:
                    pass
            articles.append({
                'title': title,
                'summary': summary,
                'url': entry.get('link', ''),
                'source': 'arXiv',
                'category': 'biomanufacturing',
                'authors': authors,
                'date': date,
                'journal': 'arXiv Preprint',
            })
        print(f"[RSS] arXiv生物: 采集 {len(articles)} 篇")
    except Exception as e:
        print(f"[RSS] arXiv采集失败: {e}")
    return articles

import re


# ==================== AI 评分与分类 ====================
def ai_score_article(article):
    """使用大模型对文章进行相关性评分"""
    try:
        prompt = RELEVANCE_PROMPT.format(title=article['title'], summary=article['summary'] or '无摘要')
        resp = requests.post(
            f'{API_BASE}/chat/completions',
            headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'},
            json={
                'model': 'deepseek-v3.2-exp-thinking',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'max_tokens': 300,
            },
            timeout=30
        )
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content']
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', content)
            if json_match:
                result = json.loads(json_match.group())
                article['category'] = result.get('category', article['category'])
                article['ai_score'] = result.get('relevance_score', 5)
                article['tags'] = result.get('tags', [])
                article['chinese_summary'] = result.get('chinese_summary', '')
                return True
    except Exception as e:
        print(f"[AI] 评分失败: {e}")
    return False


# ==================== 数据存储 ====================
def save_articles(conn, articles, auto_score=True):
    """保存文章到数据库（去重）"""
    c = conn.cursor()
    new_count = 0
    for a in articles:
        h = make_hash(a['title'], a['source'])
        # Check duplicate
        c.execute('SELECT id FROM articles WHERE content_hash = ?', (h,))
        if c.fetchone():
            continue

        # AI scoring for new articles
        if auto_score and (a.get('summary') or len(a['title']) > 20):
            ai_score_article(a)

        try:
            c.execute('''INSERT INTO articles (title, summary, chinese_summary, url, source, category,
                          journal, authors, publish_date, tags, ai_score, content_hash)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (a['title'], a.get('summary', ''), a.get('chinese_summary', ''), a.get('url', ''),
                       a['source'], a['category'], a.get('journal', ''),
                       json.dumps(a.get('authors', []), ensure_ascii=False), a.get('date', ''),
                       json.dumps(a.get('tags', []), ensure_ascii=False), a.get('ai_score'), h))
            new_count += 1
        except sqlite3.IntegrityError:
            pass  # URL duplicate
    conn.commit()
    print(f"[DB] 新增 {new_count} 篇文章，跳过 {len(articles) - new_count} 篇重复")
    return new_count


# ==================== 全量采集 ====================
def run_full_collection(auto_score=True):
    """执行全量数据采集"""
    print(f"\n{'='*60}")
    print(f"[采集] 开始全量采集 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # Add scripts to path
    scripts_dir = str(BASE_DIR / 'scripts')
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    conn = get_connection()
    all_new = []

    # RSS sources
    for name, config in RSS_SOURCES.items():
        if config.get('url'):
            articles = fetch_rss(name, config)
            all_new.extend(articles)
        elif name == '药智网':
            articles = fetch_yaozh_news()
            all_new.extend(articles)

    # arXiv
    all_new.extend(fetch_arxiv_bio())

    # Enhanced collection (PubMed + industry news + Chinese sources)
    try:
        from enhanced_collect import run_enhanced_collection
        enhanced = run_enhanced_collection()
        all_new.extend(enhanced)
    except Exception as e:
        print(f"[增强采集] 跳过: {e}")

    # Save to DB
    if all_new:
        new_count = save_articles(conn, all_new, auto_score=auto_score)
    else:
        new_count = 0

    conn.close()
    print(f"\n[采集] 完成！共采集 {len(all_new)} 篇，新增 {new_count} 篇")
    return new_count


# ==================== 导出 JSON ====================
def export_scholars_json():
    """导出学者数据为 JSON（供前端静态加载）"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM scholars ORDER BY name')
    scholars = [dict(s) for s in c.fetchall()]
    
    # Get latest papers for each scholar
    for s in scholars:
        c.execute('''SELECT title, publish_date, url FROM articles 
                    WHERE tags LIKE ? AND category = 'scholar' 
                    ORDER BY publish_date DESC LIMIT 3''', 
                  (f'%{s["name"]}%',))
        s['recent_papers'] = [dict(r) for r in c.fetchall()]
    
    conn.close()
    
    output = DATA_DIR / 'scholars.json'
    with open(output, 'w', encoding='utf-8') as f:
        json.dump({'scholars': scholars, 'updated_at': datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
    
    print(f"[导出] {len(scholars)} 位学者已导出至 {output}")
    return output


def export_to_json():
    """导出文章为 JSON（供前端使用）"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM articles ORDER BY publish_date DESC, ai_score DESC')
    rows = c.fetchall()

    articles = []
    for row in rows:
        a = dict(row)
        # authors 存储为逗号分隔字符串，转换为列表
        if a['authors']:
            a['authors'] = [x.strip() for x in a['authors'].split(',') if x.strip()]
        else:
            a['authors'] = []
        # tags 可能是 JSON 字符串或空
        try:
            a['tags'] = json.loads(a['tags']) if a['tags'] else []
        except (json.JSONDecodeError, TypeError):
            a['tags'] = []
        a['date'] = a['publish_date']
        articles.append(a)

    output = DATA_DIR / 'articles.json'
    with open(output, 'w', encoding='utf-8') as f:
        json.dump({'articles': articles, 'updated_at': datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)

    conn.close()
    print(f"[导出] {len(articles)} 篇文章已导出至 {output}")
    
    # 同时导出学者数据（供静态托管使用）
    export_scholars_json()
    
    return output


# ==================== 周报生成 ====================
def generate_report(period='weekly'):
    """生成定期报告"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if period == 'weekly':
        days = 7
        period_label = '周报'
    else:
        days = 30
        period_label = '月报'

    since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    # First try with AI score >= 6, fallback to all recent articles
    c.execute('SELECT * FROM articles WHERE publish_date >= ? AND ai_score >= 6 ORDER BY ai_score DESC LIMIT 30', (since,))
    rows = c.fetchall()
    if not rows:
        c.execute('SELECT * FROM articles WHERE publish_date >= ? ORDER BY publish_date DESC LIMIT 30', (since,))
        rows = c.fetchall()

    if not rows:
        print(f"[报告] {period_label}期间暂无高分文章")
        return None

    # Group by category
    cats = {'innovation': '创新药', 'biomanufacturing': '生物制造', 'health': '大健康', 'scholar': '学者'}
    grouped = {k: [] for k in cats}
    for row in rows:
        a = dict(row)
        cat = a['category'] or 'innovation'
        if cat in grouped:
            grouped[cat].append(a)

    report_lines = [
        f"# BioKB {period_label}",
        f"**周期**: {since} ~ {datetime.now().strftime('%Y-%m-%d')}",
        f"**高分文章数**: {len(rows)}",
        "",
    ]

    for cat_key, cat_name in cats.items():
        items = grouped[cat_key]
        if not items:
            continue
        report_lines.append(f"## {cat_name} ({len(items)}篇)")
        report_lines.append("")
        for a in items:
            score_display = a['ai_score'] if a['ai_score'] else '-'
            summary = a.get('chinese_summary') or a.get('summary', '')[:100]
            report_lines.append(f"### [{score_display}] {a['title']}")
            report_lines.append(f"- **来源**: {a['source']} | **日期**: {a['publish_date']}")
            if summary:
                report_lines.append(f"- **摘要**: {summary}")
            if a.get('url'):
                report_lines.append(f"- **链接**: {a['url']}")
            report_lines.append("")

    report_text = '\n'.join(report_lines)

    # Save report
    filename = f"{period_label}_{datetime.now().strftime('%Y-%m-%d')}.md"
    filepath = REPORTS_DIR / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report_text)

    # Save to DB
    c.execute('INSERT INTO reports (type, period, content) VALUES (?, ?, ?)',
              (period, period_label, report_text))
    conn.commit()
    conn.close()

    print(f"[报告] {period_label}已生成: {filepath}")
    return filepath


# ==================== HTTP API 服务器 ====================
def start_api_server(host='0.0.0.0', port=8765):
    """启动轻量 HTTP API 服务器"""
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import json as json_mod

    class APIHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(BASE_DIR), **kwargs)

        def do_GET(self):
            if self.path == '/api/articles':
                conn = get_connection()
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute('SELECT * FROM articles ORDER BY publish_date DESC, ai_score DESC')
                rows = c.fetchall()
                articles = []
                for row in rows:
                    a = dict(row)
                    a['authors'] = json_mod.loads(a['authors']) if a['authors'] else []
                    a['tags'] = json_mod.loads(a['tags']) if a['tags'] else []
                    a['date'] = a['publish_date']
                    articles.append(a)
                conn.close()
                self._json_response({'articles': articles, 'total': len(articles)})
            elif self.path == '/api/stats':
                conn = get_connection()
                c = conn.cursor()
                c.execute('SELECT category, COUNT(*) as cnt FROM articles GROUP BY category')
                stats = {row[0]: row[1] for row in c.fetchall()}
                c.execute('SELECT MAX(publish_date) FROM articles')
                last = c.fetchone()[0]
                c.execute('SELECT COUNT(*) FROM articles')
                total = c.fetchone()[0]
                conn.close()
                self._json_response({'by_category': stats, 'total': total, 'last_date': last})
            elif self.path == '/api/reports':
                conn = get_connection()
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute('SELECT * FROM reports ORDER BY created_at DESC LIMIT 10')
                reports = [dict(r) for r in c.fetchall()]
                conn.close()
                self._json_response({'reports': reports})
            elif self.path == '/api/scholars':
                conn = get_connection()
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute('SELECT * FROM scholars ORDER BY name')
                scholars = [dict(s) for s in c.fetchall()]
                # Get latest paper for each scholar
                for s in scholars:
                    c.execute('''SELECT title, publish_date, url FROM articles
                                WHERE tags LIKE ? AND category = 'scholar'
                                ORDER BY publish_date DESC LIMIT 3''',
                              (f'%{s["name"]}%',))
                    s['recent_papers'] = [dict(r) for r in c.fetchall()]
                conn.close()
                self._json_response({'scholars': scholars})
            elif self.path == '/api/phage-trials':
                # 加载噬菌体临床试验数据
                phage_file = DATA_DIR / 'phage_trials.json'
                if phage_file.exists():
                    try:
                        with open(phage_file, 'r', encoding='utf-8') as f:
                            data = json_mod.loads(f.read())
                        self._json_response(data)
                    except Exception as e:
                        self._json_response({'error': str(e)}, status=500)
                else:
                    self._json_response({'error': '噬菌体试验数据尚未采集', 'trials': [], 'changes': []})
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == '/api/chat':
                content_len = int(self.headers.get('Content-Length', 0))
                body = json_mod.loads(self.rfile.read(content_len))
                message = body.get('message', '')

                # Build context from knowledge base
                conn = get_connection()
                conn.row_factory = sqlite3.Row
                c = conn.cursor()

                # Search relevant articles
                keywords = message.split()
                placeholders = ' OR '.join(['title LIKE ?' for _ in keywords[:5]])
                params = [f'%{k}%' for k in keywords[:5]]
                c.execute(f'SELECT title, chinese_summary, summary, source, publish_date FROM articles WHERE {placeholders} ORDER BY ai_score DESC LIMIT 10', params)
                relevant = c.fetchall()
                conn.close()

                if relevant:
                    context = '\n'.join([f"[{r['source']} {r['publish_date']}] {r['title']}\n摘要: {r['chinese_summary'] or r['summary'] or ''}" for r in relevant])
                    prompt = f"""你是一个生物医药领域的知识库助手。基于以下知识库内容回答用户问题。如果知识库中没有相关信息，请如实说明。

知识库相关内容：
{context}

用户问题：{message}

请用中文回答，简洁专业。"""
                else:
                    prompt = f"你是一个生物医药领域的知识库助手。用户问题：{message}\n\n知识库中暂无完全匹配的内容，请根据你的知识回答，并说明这并非来自知识库。"

                try:
                    resp = requests.post(
                        f'{API_BASE}/chat/completions',
                        headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'},
                        json={
                            'model': 'deepseek-v3.2-exp-thinking',
                            'messages': [{'role': 'user', 'content': prompt}],
                            'temperature': 0.5,
                            'max_tokens': 800,
                        },
                        timeout=60
                    )
                    if resp.status_code == 200:
                        reply = resp.json()['choices'][0]['message']['content']
                        self._json_response({'reply': reply, 'sources_used': len(relevant)})
                    else:
                        self._json_response({'error': 'AI服务暂时不可用', 'sources_used': 0})
                except Exception as e:
                    self._json_response({'error': str(e), 'sources_used': 0})

            elif self.path == '/api/collect':
                # Trigger collection
                threading.Thread(target=lambda: run_full_collection(auto_score=True), daemon=True).start()
                self._json_response({'status': 'started', 'message': '数据采集已开始'})
            else:
                self.send_error(404)

        def _json_response(self, data):
            response = json_mod.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *args):
            pass  # Suppress logs

    server = HTTPServer((host, port), APIHandler)
    print(f"[API] 服务已启动: http://{host}:{port}")
    print(f"[API] 知识库页面: http://{host}:{port}/index.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[API] 服务已停止")


# ==================== CLI ====================
def main():
    if len(sys.argv) < 2:
        print("BioKB - 生物医药知识库管理系统")
        print("=" * 50)
        print("用法:")
        print("  python server.py init       - 初始化数据库")
        print("  python server.py collect    - 执行一次数据采集")
        print("  python server.py collect-fast - 快速采集（不AI评分）")
        print("  python server.py export     - 导出JSON数据")
        print("  python server.py report     - 生成周报")
        print("  python server.py report-m   - 生成月报")
        print("  python server.py scholars   - 追踪学者动态")
        print("  python server.py resume     - 生成/更新学者履历")
        print("  python server.py serve      - 启动Web服务 + API")
        print("  python server.py all        - 采集 + 导出 + 启动服务")
        return

    cmd = sys.argv[1]

    if cmd == 'init':
        init_db()
    elif cmd == 'collect':
        init_db()
        run_full_collection(auto_score=True)
        export_to_json()
    elif cmd == 'collect-fast':
        init_db()
        run_full_collection(auto_score=True)  # 启用AI评分，生成中文摘要
        export_to_json()
    elif cmd == 'export':
        export_to_json()
    elif cmd == 'report':
        init_db()
        generate_report('weekly')
    elif cmd == 'report-m':
        init_db()
        generate_report('monthly')
    elif cmd == 'serve':
        init_db()
        migrate_db()
        export_to_json()
        start_api_server()
    elif cmd == 'scholars':
        init_db()
        scripts_dir = str(BASE_DIR / 'scripts')
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from scholar_tracker import run_scholar_tracking
        run_scholar_tracking()
        export_to_json()
    elif cmd == 'all':
        init_db()
        migrate_db()
        run_full_collection(auto_score=True)
        export_to_json()
        generate_report('weekly')
        start_api_server()
    elif cmd == 'resume':
        init_db()
        migrate_db()
        scripts_dir = str(BASE_DIR / 'scripts')
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from scholar_resume import batch_generate_resumes
        batch_generate_resumes()
    elif cmd == 'phage-trials':
        # 采集噬菌体临床试验数据（使用V2版本，支持增量采集和审核）
        scripts_dir = str(BASE_DIR / 'scripts')
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from phage_trials_v2 import run_collection_v2
        run_collection_v2(auto_approve=True)
    elif cmd == 'all':
        init_db()
        migrate_db()
        run_full_collection(auto_score=True)
        export_to_json()
        generate_report('weekly')
        # 同时采集噬菌体临床试验（使用V2版本）
        from phage_trials_v2 import run_collection_v2 as run_phage
        run_phage(auto_approve=True)
        start_api_server()
    else:
        print(f"未知命令: {cmd}")


if __name__ == '__main__':
    main()
