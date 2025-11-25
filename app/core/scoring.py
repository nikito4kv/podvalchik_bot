from typing import List, Dict, Tuple

def calculate_forecast_points(
    prediction_data: List[int], results_data: Dict[int, int]
) -> Tuple[int, List[int], int]:
    """
    Рассчитывает очки за один прогноз.

    :param prediction_data: Список ID игроков в порядке прогноза [1-е место, 2-е место, ...].
    :param results_data: Словарь с реальными результатами {player_id: rank}.
    :return: Кортеж (total_points, diffs, exact_hits).
    """
    total_points = 0
    diffs = []
    exact_hits = 0

    # Проходим по 5 спрогнозированным слотам
    for i, player_id in enumerate(prediction_data):
        predicted_rank = i + 1

        # Если игрок из прогноза есть в итоговых результатах
        if player_id in results_data:
            actual_rank = results_data[player_id]
            diff = abs(predicted_rank - actual_rank)
            diffs.append(diff)

            # Очки: теперь в 10 раз меньше, чем раньше
            slot_points = max(0, (100 - (diff * 15)) // 10)

            # Бонус за точное попадание: теперь 2 очка вместо 20
            if diff == 0:
                slot_points += 2
                exact_hits += 1

            total_points += slot_points
        else:
            # Игрока нет в итоговой таблице, за слот 0 очков
            # Diff можно считать бесконечным, но для MAE лучше взять максимальное значение
            # Для простоты пока будем считать diff как 5 (максимальный ранг)
            diffs.append(len(prediction_data)) # Условный максимальный штраф
            total_points += 0

    return total_points, diffs, exact_hits


def calculate_new_stats(
    old_total_points: int,
    old_accuracy: float,
    old_mae: float,
    forecasts_count: int,
    new_forecast_points: int,
    new_forecast_diffs: List[int],
    new_forecast_exact_hits: int,
) -> Tuple[int, float, float]:
    """
    Пересчитывает общую статистику пользователя.

    :param old_total_points: Текущие очки пользователя.
    :param old_accuracy: Текущая точность.
    :param old_mae: Текущая средняя ошибка.
    :param forecasts_count: Общее количество сделанных прогнозов (до нового).
    :param new_forecast_points: Очки за новый прогноз.
    :param new_forecast_diffs: Список ошибок (diff) для нового прогноза.
    :param new_forecast_exact_hits: Количество точных попаданий в новом прогнозе.
    :return: Кортеж (new_total_points, new_accuracy, new_mae).
    """
    # Обновляем общий счет
    new_total_points = old_total_points + new_forecast_points

    # Пересчитываем MAE (Среднюю абсолютную ошибку)
    # (Старая сумма ошибок + новая сумма ошибок) / (новое общее кол-во слотов)
    # Старая сумма ошибок = old_mae * forecasts_count * 5
    # forecasts_count - это количество ТУРНИРОВ, в которых участвовал юзер
    # Общее кол-во прогнозируемых слотов = forecasts_count * 5
    
    total_slots_before = forecasts_count * 5
    sum_of_errors_before = old_mae * total_slots_before
    
    sum_of_new_errors = sum(new_forecast_diffs)
    total_slots_after = (forecasts_count + 1) * 5
    
    new_mae = (sum_of_errors_before + sum_of_new_errors) / total_slots_after

    # Пересчитываем Accuracy (Точность)
    # (Старое кол-во точных попаданий + новое кол-во) / (новое общее кол-во слотов)
    # Старое кол-во точных попаданий = (old_accuracy / 100) * total_slots_before
    
    total_exact_hits_before = (old_accuracy / 100) * total_slots_before
    total_exact_hits_after = total_exact_hits_before + new_forecast_exact_hits
    
    new_accuracy = (total_exact_hits_after / total_slots_after) * 100

    return new_total_points, round(new_accuracy, 2), round(new_mae, 2)
