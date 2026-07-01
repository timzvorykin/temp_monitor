import mysql.connector
import requests
import time
from datetime import datetime
import os
import json

# ============================================================
# НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ
# ============================================================
DB_CONFIG = {
    'host': '',
    'user': '',
    'password': '',
    'database': '',
    'port': 
}

# ============================================================
# ЗАГРУЗКА ТОКЕНА VK ИЗ ФАЙЛА
# ============================================================
def load_token():
    """Читает токен группы VK из файла vk_token.txt"""
    if os.path.exists('vk_token.txt'):
        with open('vk_token.txt', 'r') as f:
            return f.read().strip()
    return None

VK_GROUP_TOKEN = load_token()
VK_GROUP_ID = 

# ============================================================
# ФАЙЛ ДЛЯ ХРАНЕНИЯ ПОДПИСЧИКОВ
# ============================================================
SUBSCRIBERS_FILE = 'subscribers.json'

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
        # Подключаемся к базе данных
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # SQL-запрос: получаем последнюю запись для каждого холодильника
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
        
        # Собираем данные по всем холодильникам
        all_data = []
        has_alert = False
        
        for row in results:
            location = row['location']
            temperature = float(row['temperature'])
            dt = row['datetime']
            fridge_name = get_fridge_name(location)
            
            print(f"{fridge_name}: {temperature}°C [{dt}]")
            
            # Определяем статус температуры
            if temperature > 8:
                status = 'critical'  # Критическое превышение
            elif temperature > 6:
                status = 'warning'   # Повышенная температура
            else:
                status = 'normal'    # Норма
            
            all_data.append({
                'fridge_name': fridge_name,
                'temperature': temperature,
                'datetime': dt,
                'status': status
            })
            
            # Проверяем, есть ли превышение порога
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
# ПОЛУЧЕНИЕ СПИСКА ВСЕХ ПОДПИСЧИКОВ ГРУППЫ VK
# ============================================================
def get_all_subscribers():
    """
    Загружает полный список подписчиков группы через VK API.
    Возвращает список с ID, именами и возможностью отправки сообщений.
    """
    print("Загрузка подписчиков группы...")
    subscribers = []
    
    try:
        offset = 0
        count = 1000
        
        while True:
            url = "https://api.vk.com/method/groups.getMembers"
            params = {
                'access_token': VK_GROUP_TOKEN,
                'v': '5.131',
                'group_id': VK_GROUP_ID,
                'sort': 'id_asc',
                'offset': offset,
                'count': count,
                'fields': 'can_write_private_message'
            }
            
            response = requests.post(url, data=params, timeout=30)
            result = response.json()
            
            if 'response' in result:
                items = result['response']['items']
                if not items:
                    break
                    
                for item in items:
                    can_write = item.get('can_write_private_message', False)
                    subscribers.append({
                        'id': item['id'],
                        'first_name': item.get('first_name', ''),
                        'last_name': item.get('last_name', ''),
                        'can_write': can_write
                    })
                
                print(f"  Загружено: {len(subscribers)} подписчиков...", end='\r')
                offset += count
                
                if offset > 10000:
                    print(f"\n  Загружено максимум 10000 подписчиков")
                    break
            else:
                error = result.get('error', {})
                print(f"\n  Ошибка загрузки: {error.get('error_msg', 'Unknown')}")
                break
        
        print(f"\n  Всего загружено: {len(subscribers)} подписчиков")
        return subscribers
        
    except Exception as e:
        print(f"  Ошибка: {e}")
        return []

# ============================================================
# ПОЛУЧЕНИЕ СПИСКА АКТИВНЫХ ПОДПИСЧИКОВ (КТО ПИСАЛ ГРУППЕ)
# ============================================================
def get_active_subscribers():
    """
    Возвращает список ID пользователей, которые могут получать сообщения.
    Это те, кто написал группе хотя бы одно сообщение.
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
    """
    Отправляет сообщение конкретному пользователю от имени группы.
    Возвращает True при успехе, False при ошибке.
    """
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
# ФОРМИРОВАНИЕ И РАССЫЛКА СООБЩЕНИЯ С ДАННЫМИ
# ============================================================
def send_alert_to_subscribers(all_data):
    """
    Создаёт сообщение с данными по всем холодильникам.
    Разделяет на повышенную и критическую температуру.
    """
    if not all_data:
        return
    
    # Дата из первого холодильника
    dt = all_data[0]['datetime']
    
    # Разделяем холодильники по статусам
    critical = [d for d in all_data if d['status'] == 'critical']
    warning = [d for d in all_data if d['status'] == 'warning']
    normal = [d for d in all_data if d['status'] == 'normal']
    
    # Формируем сообщение
    message = f"{dt}\n\n"
    
    # Критические превышения
    if critical:
        message += "Критично повышено:\n"
        for data in critical:
            message += f"{data['fridge_name']}: {data['temperature']}°C\n"
        message += "\n"
    
    # Повышенная температура
    if warning:
        message += "Повышено:\n"
        for data in warning:
            message += f"{data['fridge_name']}: {data['temperature']}°C\n"
        message += "\n"
    
    # Нормальная температура
    if normal:
        message += "В норме:\n"
        for data in normal:
            message += f"{data['fridge_name']}: {data['temperature']}°C\n"
    
    # Получаем список активных подписчиков
    active_subscribers = get_active_subscribers()
    
    # Если нет активных подписчиков - сохраняем в файл
    if not active_subscribers:
        print("Нет активных подписчиков для отправки")
        filename = f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(message)
        print(f"Уведомление сохранено в {filename}")
        return
    
    # Рассылаем уведомления
    print(f"\nОтправка уведомлений {len(active_subscribers)} подписчикам...")
    
    success_count = 0
    for user_id in active_subscribers:
        if send_private_message(user_id, message):
            success_count += 1
        time.sleep(0.05)
    
    print(f"Отправлено: {success_count}/{len(active_subscribers)}")
    
    # Резервная копия
    if success_count == 0:
        filename = f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(message)
        print(f"Уведомление сохранено в {filename}")

# ============================================================
# ПРОВЕРКА ПРАВ НА ОТПРАВКУ СООБЩЕНИЙ
# ============================================================
def test_messaging():
    """Проверяет, есть ли у токена права на отправку сообщений."""
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
    """Основная функция: запускает мониторинг и бесконечно проверяет температуру"""
    print("=" * 60)
    print("МОНИТОРИНГ ТЕМПЕРАТУРЫ ХОЛОДИЛЬНИКОВ")
    print("=" * 60)
    print(f"Запуск: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Контроль: Холодильник 1, Холодильник 2, Холодильник 3")
    print(f"Порог срабатывания: > 6°C")
    print(f"Критический порог: > 8°C")
    print("=" * 60)
    
    # Проверяем права на отправку сообщений
    messages_ok = test_messaging()
    
    # Проверяем подключение к базе данных
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
    
    # Выводим статус системы
    print("\n" + "=" * 60)
    print("СТАТУС СИСТЕМЫ:")
    print(f"  Отправка сообщений: {'Включена' if messages_ok else 'Отключена'}")
    print(f"  Сохранение в файл: Включено (резерв)")
    print("=" * 60)
    
    if not messages_ok:
        print("\nТребуется настройка прав сообщений в группе VK")
        return
    
    # Выводим статистику по подписчикам
    print("\nСтатистика подписчиков:")
    all_subscribers = get_all_subscribers()
    active_subscribers = get_active_subscribers()
    
    print(f"  Всего подписчиков группы: {len(all_subscribers)}")
    print(f"  Получают уведомления: {len(active_subscribers)}")
    
    if len(active_subscribers) == 0:
        print("\nДля получения уведомлений необходимо:")
        print("  1. Вступить в группу")
        print("  2. Написать любое сообщение группе")
    
    print("\nМониторинг запущен...\n")
    
    # Переменная для отслеживания предыдущего состояния
    previous_has_alert = False
    
    # Бесконечный цикл проверки температуры
    while True:
        try:
            print(f"\n{'─'*40}")
            print(f"{datetime.now().strftime('%H:%M:%S')}")
            
            # Получаем данные о температуре
            all_data, has_alert = check_temperature()
            
            # Отправляем уведомление если есть превышение или температура вернулась в норму
            if has_alert:
                print(f"Обнаружено превышение температуры")
                send_alert_to_subscribers(all_data)
                previous_has_alert = True
            elif previous_has_alert:
                # Температура нормализовалась после превышения
                print("Температура вернулась в норму")
                send_alert_to_subscribers(all_data)
                previous_has_alert = False
            else:
                print("Температура в норме")
            
            # Ждём 5 минут до следующей проверки
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