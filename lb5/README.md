python -m venv .venv
# Windows:
# .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt

# Обычный прогон
scrapy crawl tags

# Прогон с JOBDIR — демонстрация возобновляемости
scrapy crawl tags -s JOBDIR=jobstate/tags_run1

# Прогон с HTTP-кэшем для отладки
scrapy crawl tags -s HTTPCACHE_ENABLED=True

# Проверка деградации
python quality/smoke_check.py

# Запуск no-code
docker run -it --rm --name n8n -p 5678:5678 ^
  -v n8n_data:/home/node/.n8n ^
  -v E:\temp\web-scrapers\lb5\nocode:/files ^
  -e N8N_RESTRICT_FILE_ACCESS_TO=/files ^
  docker.n8n.io/n8nio/n8n