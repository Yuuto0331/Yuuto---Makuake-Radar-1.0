# ==================================================
# 最终版：Makuake 自动备份 - 不删任何备份 + 按项目拆分
# ==================================================
name: Backup Makuake Database

on:
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          persist-credentials: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pandas sqlite3 requests

      - name: Download and split database
        env:
          APP_URL: ${{ secrets.STREAMLIT_APP_URL }}
        run: |
          DATE=$(date +'%Y%m%d_%H%M%S')
          BACKUP_DIR="backups/backup_${DATE}"
          mkdir -p "$BACKUP_DIR"
          
          # 下载数据库
          FULL_DB="${BACKUP_DIR}/makuake_full_${DATE}.db"
          curl -L -o "$FULL_DB" "${APP_URL}?download_db=1"
          echo "✅ 完整数据库下载完成"
          
          # 按项目拆分
          python -c "
          import sqlite3
          import pandas as pd
          import os

          conn = sqlite3.connect('$FULL_DB')
          projects_df = pd.read_sql('SELECT id, title FROM projects', conn)
          
          if not projects_df.empty:
              for _, proj in projects_df.iterrows():
                  proj_id = proj['id']
                  proj_name = str(proj.get('title', f'proj_{proj_id}')).replace('/', '_').replace(' ', '_')
                  
                  hist_df = pd.read_sql(f'SELECT * FROM history WHERE project_id = {proj_id}', conn)
                  
                  proj_file = f'$BACKUP_DIR/project_{proj_id}_{proj_name}_{DATE}.csv'
                  hist_df.to_csv(proj_file, index=False, encoding='utf-8-sig')
                  print(f'✅ 项目 {proj_name} 备份完成')
          else:
              print('⚠️ 暂无项目数据')
          
          conn.close()
          "

      - name: Push backup
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
