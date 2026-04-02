name: Backup Makuake Database
on:
  schedule:
    - cron: '0 2 * * *'  # 北京时间10点自动备份
  workflow_dispatch:     # 允许手动触发

permissions:
  contents: write        # 赋予推送代码的权限

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pandas requests  # 仅安装需要的依赖（sqlite3是内置的，无需安装）

      - name: Download and backup database
        env:
          # 替换成你的Streamlit应用地址（末尾带/）
          APP_URL: ${{ secrets.STREAMLIT_APP_URL }}
        run: |
          DATE=$(date +'%Y%m%d_%H%M%S')
          BACKUP_DIR="backups/backup_${DATE}"
          mkdir -p "$BACKUP_DIR"
          
          # 调用应用的下载接口获取数据库
          FULL_DB="${BACKUP_DIR}/makuake_full_${DATE}.db"
          curl -L --max-time 60 -o "$FULL_DB" "${APP_URL}?download_db=1"
          
          # 验证下载是否成功
          if [ ! -f "$FULL_DB" ]; then
            echo "❌ 数据库下载失败"
            exit 1
          fi
          echo "✅ 数据库下载成功"

      - name: Push backup to GitHub
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          
          git add backups/
          if git diff --cached --quiet; then
            echo "无新备份，跳过提交"
            exit 0
          fi
          
          git commit -m "Auto backup ${DATE}"
          git push origin main
