from typing import List, Dict, Tuple

def calculate_forecast_points(
    prediction_data: List[int], results_data: Dict[int, int]
) -> Tuple[int, List[int], int]:
    """
    Рассчитывает очки за один прогноз по системе РТТФ.
    
    Правила:
    - Угадывание призера (вхождение в топ) - 1 очко.
    - Угадывание призера и занятого им места - 5 очков.
    - Бонус за угадывание ВСЕХ призеров и их мест - 15 очков.

    :param prediction_data: Список ID игроков в порядке прогноза.
    :param results_data: Словарь с реальными результатами {player_id: rank}.
    :return: Кортеж (total_points, diffs, exact_hits).
    """
    total_points = 0
    diffs = []
    exact_hits = 0
    
    slots_count = len(prediction_data)

    # Проходим по прогнозируемым слотам
    for i, player_id in enumerate(prediction_data):
        predicted_rank = i + 1

        # Если игрок из прогноза есть в итоговых результатах
        if player_id in results_data:
            actual_rank = results_data[player_id]
            diff = abs(predicted_rank - actual_rank)
            diffs.append(diff)

            if diff == 0:
                # Точное попадание
                total_points += 5
                exact_hits += 1
            else:
                # Просто угадал призера, но не место
                total_points += 1
        else:
            # Игрока нет в итоговой таблице
            # Diff считаем как макс ранг для MAE
            diffs.append(slots_count) 
            total_points += 0

    # Проверка на бонус (угадывание всех призеров и их мест)
    if exact_hits == slots_count and slots_count > 0:
        total_points += 15

    return total_points, diffs, exact_hits


def calculate_new_stats(
    old_total_points: int,
    old_accuracy: float,
    old_mae: float,
    total_slots_before: int, # Changed from forecasts_count
    new_forecast_points: int,
    new_forecast_diffs: List[int],
    new_forecast_exact_hits: int,
) -> Tuple[int, float, float]:
    """
    Пересчитывает общую статистику пользователя.

    :param old_total_points: Текущие очки пользователя.
    :param old_accuracy: Текущая точность.
    :param old_mae: Текущая средняя ошибка.
    :param total_slots_before: Общее количество слотов во всех предыдущих прогнозах (сумма N_i).
    :param new_forecast_points: Очки за новый прогноз.
    :param new_forecast_diffs: Список ошибок (diff) для нового прогноза.
    :param new_forecast_exact_hits: Количество точных попаданий в новом прогнозе.
    :return: Кортеж (new_total_points, new_accuracy, new_mae).
    """
    # Обновляем общий счет
    new_total_points = old_total_points + new_forecast_points
    
    # Количество слотов в новом прогнозе
    new_slots_count = len(new_forecast_diffs)

    # Пересчитываем MAE (Среднюю абсолютную ошибку)
    # (Старая сумма ошибок + новая сумма ошибок) / (новое общее кол-во слотов)
    
    sum_of_errors_before = old_mae * total_slots_before
    sum_of_new_errors = sum(new_forecast_diffs)
    total_slots_after = total_slots_before + new_slots_count
    
    new_mae = (sum_of_errors_before + sum_of_new_errors) / total_slots_after if total_slots_after > 0 else 0.0

    # Пересчитываем Accuracy (Точность)
    # (Старое кол-во точных попаданий + новое кол-во) / (новое общее кол-во слотов)
    
    total_exact_hits_before = (old_accuracy / 100) * total_slots_before
    total_exact_hits_after = total_exact_hits_before + new_forecast_exact_hits
    
    new_accuracy = (total_exact_hits_after / total_slots_after) * 100 if total_slots_after > 0 else 0.0

    return new_total_points, round(new_accuracy, 2), round(new_mae, 2)
