import mysql.connector
import requests
import time
from datetime import datetime
import os
import json

# ============================================================
# ЗАГРУЗКА КОНФИГУРАЦИИ ИЗ ФАЙЛА
# ============================================================
def load_config():
    """
    Загружает все настройки из файла config.json.
    Если файл не найден, выводит инструкцию по созданию.
    """
    config_file = 'config.json'
    
    if not os.path.exists(config_file):
        print("=" * 60)
        print("ОШИБКА: Файл config.json не найден!")
        print("=" * 60)

        return None
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Проверяем наличие всех полей
        required_db = ['host', 'user', 'password', 'database']
        required_vk = ['token', 'group_id']
        
        db_config = config.get('database', {})
        vk_config = config.get('vk', {})
        
        # Проверка полей БД
        for field in required_db:
            if field not in db_config:
                print(f"ОШИБКА: В config.json отсутствует поле database.{field}")
                return None
        
        # Проверка полей VK
        for field in required_vk:
            if field not in vk_config:
                print(f"ОШИБКА: В config.json отсутствует поле vk.{field}")
                return None
        
        # Добавляем порт по умолчанию, если не указан
        if 'port' not in db_config:
            db_config['port'] = 3306
        
        print("Конфигурация загружена из config.json")
        return config
        
    except json.JSONDecodeError as e:
        print(f"ОШИБКА: config.json содержит неверный JSON: {e}")
        return None
    except Exception as e:
        print(f"ОШИБКА при чтении config.json: {e}")
        return None

# Загружаем конфигурацию
CONFIG = load_config()

if CONFIG is None:
    exit(1)

# Извлекаем настройки
DB_CONFIG = CONFIG['database']
VK_GROUP_TOKEN = CONFIG['vk']['token']
VK_GROUP_ID = CONFIG['vk']['group_id']

# ============================================================
# ПЕРЕВОД ТЕХНИЧЕСКИХ НАЗВАНИЙ ХОЛОДИЛЬНИКОВ НА РУССКИЙ
# ============================================================
FRIDGE_NAMES = {
    'rzsh4_fridge_1': 'Холодильник 1',
    'rzsh4_fridge_2': 'Холодильник 2',
    'rzsh4_fridge_3': 'Холодильник 3'
}

def get_fridge_name(location):
    """Возвращает русское название холодильника по его техническому имени"""
    return FRIDGE_NAMES.get(location, location)

# ============================================================
# ПОЛУЧЕНИЕ ДАННЫХ О ТЕМПЕРАТУРЕ ИЗ БАЗЫ ДАННЫХ
# ============================================================
def check_temperature():
    """
    Запрашивает последние показания температуры для трёх холодильников.
    Возвращает данные по всем холодильникам.
    """
    connection = None
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = """
        SELECT 
            location,
            temperature,
            datetime 
        FROM Temp_Sclad 
        WHERE location IN ('rzsh4_fridge_1', 'rzsh4_fridge_2', 'rzsh4_fridge_3')
        AND (location, datetime) IN (
            SELECT location, MAX(datetime)
            FROM Temp_Sclad
            WHERE location IN ('rzsh4_fridge_1', 'rzsh4_fridge_2', 'rzsh4_fridge_3')
            GROUP BY location
        )
        ORDER BY location
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        all_data = []
        has_alert = False
        
        for row in results:
            location = row['location']
            temperature = float(row['temperature'])
            dt = row['datetime']
            fridge_name = get_fridge_name(location)
            
            print(f"{fridge_name}: {temperature}°C [{dt}]")
            
            if temperature > 8:
                status = 'critical'
            elif temperature > 6:
                status = 'warning'
            else:
                status = 'normal'
            
            all_data.append({
                'fridge_name': fridge_name,
                'temperature': temperature,
                'datetime': dt,
                'status': status
            })
            
            if temperature > 6:
                has_alert = True
        
        cursor.close()
        return all_data, has_alert
        
    except Exception as e:
        print(f"Ошибка при запросе к БД: {e}")
        return [], False
    finally:
        if connection and connection.is_connected():
            connection.close()

# ============================================================
# ПОЛУЧЕНИЕ СПИСКА АКТИВНЫХ ПОДПИСЧИКОВ
# ============================================================
def get_active_subscribers():
    """
    Возвращает список ID пользователей, которые могут получать сообщения.
    """
    print("Проверка активных подписчиков...")
    active_subscribers = []
    
    try:
        url = "https://api.vk.com/method/messages.getConversations"
        params = {
            'access_token': VK_GROUP_TOKEN,
            'v': '5.131',
            'group_id': VK_GROUP_ID,
            'count': 200
        }
        
        response = requests.post(url, data=params, timeout=30)
        result = response.json()
        
        if 'response' in result:
            conversations = result['response']['items']
            
            for conv in conversations:
                peer = conv.get('conversation', {}).get('peer', {})
                peer_id = peer.get('id', 0)
                
                if peer_id < 2000000000:
                    active_subscribers.append(peer_id)
            
            print(f"  Активных пользователей: {len(active_subscribers)}")
        else:
            print(f"  Ошибка: {result.get('error', {}).get('error_msg', 'Unknown')}")
            
    except Exception as e:
        print(f"  Ошибка: {e}")
    
    return active_subscribers

# ============================================================
# ОТПРАВКА ЛИЧНОГО СООБЩЕНИЯ В VK
# ============================================================
def send_private_message(user_id, message):
    """Отправляет сообщение пользователю от имени группы."""
    try:
        url = "https://api.vk.com/method/messages.send"
        params = {
            'access_token': VK_GROUP_TOKEN,
            'v': '5.131',
            'user_id': user_id,
            'message': message,
            'random_id': int(datetime.now().timestamp() * 1000),
            'group_id': VK_GROUP_ID
        }
        
        response = requests.post(url, data=params, timeout=10)
        result = response.json()
        
        if 'response' in result:
            return True
        else:
            error_code = result.get('error', {}).get('error_code', 0)
            if error_code in [901, 902, 15]:
                return False
            else:
                print(f"  Ошибка отправки {user_id}: {result.get('error', {}).get('error_msg', 'Unknown')}")
                return False
            
    except Exception as e:
        print(f"  Ошибка для {user_id}: {e}")
        return False

# ============================================================
# ФОРМИРОВАНИЕ И РАССЫЛКА СООБЩЕНИЯ
# ============================================================
def send_alert_to_subscribers(all_data):
    """Создаёт и рассылает сообщение с данными."""
    if not all_data:
        return
    
    dt = all_data[0]['datetime']
    
    critical = [d for d in all_data if d['status'] == 'critical']
    warning = [d for d in all_data if d['status'] == 'warning']
    normal = [d for d in all_data if d['status'] == 'normal']
    
    message = f"{dt}\n\n"
    
    if critical:
        message += "Критично повышено:\n"
        for data in critical:
            message += f"{data['fridge_name']}: {data['temperature']}°C\n"
        message += "\n"
    
    if warning:
        message += "Повышено:\n"
        for data in warning:
            message += f"{data['fridge_name']}: {data['temperature']}°C\n"
        message += "\n"
    
    if normal:
        message += "В норме:\n"
        for data in normal:
            message += f"{data['fridge_name']}: {data['temperature']}°C\n"
    
    active_subscribers = get_active_subscribers()
    
    if not active_subscribers:
        print("Нет активных подписчиков для отправки")
        filename = f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(message)
        print(f"Уведомление сохранено в {filename}")
        return
    
    print(f"\nОтправка уведомлений {len(active_subscribers)} подписчикам...")
    
    success_count = 0
    for user_id in active_subscribers:
        if send_private_message(user_id, message):
            success_count += 1
        time.sleep(0.05)
    
    print(f"Отправлено: {success_count}/{len(active_subscribers)}")
    
    if success_count == 0:
        filename = f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(message)
        print(f"Уведомление сохранено в {filename}")

# ============================================================
# ПРОВЕРКА ПРАВ НА ОТПРАВКУ СООБЩЕНИЙ
# ============================================================
def test_messaging():
    """Проверяет права токена на отправку сообщений."""
    print("\nПроверка прав на отправку сообщений...")
    
    try:
        url = "https://api.vk.com/method/messages.getConversations"
        params = {
            'access_token': VK_GROUP_TOKEN,
            'v': '5.131',
            'group_id': VK_GROUP_ID,
            'count': 1
        }
        response = requests.post(url, data=params, timeout=10)
        result = response.json()
        
        if 'response' in result:
            print("  Права на сообщения есть")
            return True
        else:
            error_msg = result.get('error', {}).get('error_msg', '')
            print(f"  Нет прав: {error_msg}")
            return False
    except Exception as e:
        print(f"  Ошибка: {e}")
        return False

# ============================================================
# ГЛАВНЫЙ ЦИКЛ МОНИТОРИНГА
# ============================================================
def main():
    """Основная функция."""
    print("=" * 60)
    print("МОНИТОРИНГ ТЕМПЕРАТУРЫ ХОЛОДИЛЬНИКОВ")
    print("=" * 60)
    print(f"Запуск: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Контроль: Холодильник 1, Холодильник 2, Холодильник 3")
    print(f"Порог срабатывания: > 6°C")
    print(f"Критический порог: > 8°C")
    print("=" * 60)
    
    messages_ok = test_messaging()
    
    print("\nПроверка подключения к БД...")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM Temp_Sclad")
        count = cursor.fetchone()[0]
        print(f"БД доступна. Записей в таблице: {count}")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}")
        return
    
    print("\n" + "=" * 60)
    print("СТАТУС СИСТЕМЫ:")
    print(f"  Отправка сообщений: {'Включена' if messages_ok else 'Отключена'}")
    print(f"  Сохранение в файл: Включено (резерв)")
    print("=" * 60)
    
    if not messages_ok:
        print("\nТребуется настройка прав сообщений в группе VK")
        return
    
    print("\nСтатистика подписчиков:")
    active_subscribers = get_active_subscribers()
    print(f"  Получают уведомления: {len(active_subscribers)}")
    
    if len(active_subscribers) == 0:
        print("\nДля получения уведомлений необходимо:")
        print("  1. Вступить в группу")
        print("  2. Написать любое сообщение группе")
    
    print("\nМониторинг запущен...\n")
    
    previous_has_alert = False
    
    while True:
        try:
            print(f"\n{'─'*40}")
            print(f"{datetime.now().strftime('%H:%M:%S')}")
            
            all_data, has_alert = check_temperature()
            
            if has_alert:
                print(f"Обнаружено превышение температуры")
                send_alert_to_subscribers(all_data)
                previous_has_alert = True
            elif previous_has_alert:
                print("Температура вернулась в норму")
                send_alert_to_subscribers(all_data)
                previous_has_alert = False
            else:
                print("Температура в норме")
            
            print("Ожидание 5 минут...")
            time.sleep(300)
            
        except KeyboardInterrupt:
            print("\nМониторинг остановлен")
            break
        except Exception as e:
            print(f"Ошибка в цикле мониторинга: {e}")
            time.sleep(60)

# ============================================================
# ТОЧКА ВХОДА
# ============================================================
if __name__ == "__main__":
    main()