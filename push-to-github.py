"""
BioKB 采集 + 自动推送到 GitHub
运行方式: python push-to-github.py
由每日自动化任务调用
"""
import subprocess
import os
import sys
from datetime import datetime

REPO_DIR = r"C:\Users\silen\biopharma-kb"
TOKEN = os.environ.get("GH_TOKEN") or open(os.path.join(os.path.dirname(__file__), "gh_token.txt")).read().strip()
COMMIT_MSG = f"data: BioKB 每日更新 {datetime.now().strftime('%Y-%m-%d %H:%M')}"

def run(cmd, cwd=REPO_DIR, check=True):
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True
    )
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0 and check:
        print(f"[ERROR] {cmd}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result

print("=" * 50)
print("[1/5] 采集知识库数据...")
run("python server.py collect-fast")

print("=" * 50)
print("[2/5] 采集噬菌体临床试验数据...")
run("python server.py phage-trials")

print("=" * 50)
print("[3/5] 导出 JSON...")
run("python server.py export")

print("=" * 50)
print("[4/5] Git 提交...")
# 设置 Git 用户信息（确保自动化环境下也有）
run('git config user.name "silenceyz525"')
run('git config user.email "silenceyz525@163.com"')

# 检查是否有变更
status = run("git status --porcelain", check=False)
if not status.stdout.strip():
    print("没有变更，跳过推送")
else:
    run("git add data/articles.json data/phage_trials.json")
    run(f'git commit -m "{COMMIT_MSG}"')

    print("=" * 50)
    print("[5/5] 推送到 GitHub...")
    remote = f"https://{TOKEN}@github.com/silenceyz525/biokb.git"
    run(f"git remote set-url origin {remote}")
    result = run("git push origin master", check=False)
    if result.returncode == 0:
        print("✅ 推送成功！")
    else:
        print(f"⚠️ 推送失败: {result.stderr}")
        print("（可能是网络问题，明日采集时会重试）")

print("=" * 50)
print("完成！")

# ==================== 清理历史记忆文件 ====================
print("=" * 50)
print("[清理] 删除前一天的历史记忆文件...")
from datetime import timedelta
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
memory_dir = os.path.join(REPO_DIR, '.workbuddy', 'memory')
yesterday_file = os.path.join(memory_dir, f"{yesterday}.md")
if os.path.exists(yesterday_file):
    os.remove(yesterday_file)
    print(f"[清理] 已删除 {yesterday}.md")
else:
    print(f"[清理] 昨天无记忆文件需要删除")
