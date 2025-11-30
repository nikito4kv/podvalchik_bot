# Test Plan and Cases for Podvalchik Bot

## 1. Test Plan Overview
This document outlines the testing strategy for the Podvalchik Bot application. The tests cover all critical functional areas: Database Interaction, Admin Features, Tournament Management, Player Management, and User Predictions.

### Testing Levels:
*   **Unit Tests:** Focus on isolated logic (e.g., scoring calculations, data formatting).
*   **Integration Tests:** Verify interactions between components, primarily the database and the application logic (CRUD operations).
*   **Functional Tests:** Simulate user workflows (e.g., a full prediction cycle, tournament creation lifecycle).

---

## 2. Unit Tests

### 2.1 Scoring Logic (`app.core.scoring`)
*   **Test Case 2.1.1: Perfect Prediction**
    *   **Input:** Prediction `[1, 2, 3, 4, 5]`, Result `{1: 1, 2: 2, 3: 3, 4: 4, 5: 5}`
    *   **Expected Output:** Max points (calculate manually based on formula), 5 exact hits, 0 diffs.
*   **Test Case 2.1.2: Complete Miss**
    *   **Input:** Prediction `[1, 2, 3, 4, 5]`, Result `{6: 1, 7: 2, 8: 3, 9: 4, 10: 5}`
    *   **Expected Output:** 0 points, 0 exact hits.
*   **Test Case 2.1.3: Partial Match**
    *   **Input:** Prediction `[1, 2]`, Result `{1: 2, 2: 1}` (Swapped 1st and 2nd place)
    *   **Expected Output:** Points calculated with penalty for rank difference.

### 2.2 Data Formatting (`app.utils.formatting`)
*   **Test Case 2.2.1: Progress Bar Generation**
    *   **Input:** 50%, 100%, 0%
    *   **Expected Output:** Correct string representation of bars.

---

## 3. Integration Tests (Database & CRUD)

### 3.1 Tournament CRUD (`app.db.crud`)
*   **Test Case 3.1.1: Create and Retrieve Tournament**
    *   **Action:** Create a tournament via CRUD.
    *   **Assertion:** Retrieve it by ID and verify name/date match.
*   **Test Case 3.1.2: Filter Open Tournaments**
    *   **Action:** Create tournaments with statuses DRAFT, OPEN, FINISHED.
    *   **Assertion:** `get_open_tournaments` returns only the OPEN one.

### 3.2 Forecast CRUD
*   **Test Case 3.2.1: Create and Retrieve Forecast**
    *   **Action:** Create a forecast for a user and tournament.
    *   **Assertion:** Verify it exists in `get_user_forecast_tournament_ids`.
*   **Test Case 3.2.2: Delete Forecast**
    *   **Action:** Create and then delete a forecast.
    *   **Assertion:** Verify it is no longer retrievable.

### 3.3 Player Management
*   **Test Case 3.3.1: Add and Retrieve Player**
    *   **Action:** Add a player.
    *   **Assertion:** Player exists in DB with correct attributes.

---

## 4. Functional Tests (Workflows)

### 4.1 Admin: Tournament Management
*   **Test Case 4.1.1: Full Tournament Lifecycle**
    1.  **Create:** Admin creates a tournament "Test Cup".
    2.  **Add Participants:** Admin adds 5 players.
    3.  **Publish:** Admin changes status to OPEN.
    4.  **Verify:** Tournament appears in `get_open_tournaments`.
    5.  **Close Bets:** Admin changes status to LIVE.
    6.  **Set Results:** Admin enters results.
    7.  **Finish:** Status becomes FINISHED, points are calculated.

### 4.2 Admin: Player Management
*   **Test Case 4.2.1: CRUD Player**
    1.  **Create:** Admin adds a new player via command.
    2.  **Edit:** Admin changes player rating.
    3.  **Archive:** Admin archives the player.
    4.  **Verify:** Player is not shown in active lists but exists in DB.

### 4.3 User: Prediction Flow
*   **Test Case 4.3.1: Successful Prediction**
    1.  **Setup:** An OPEN tournament exists with participants.
    2.  **Start:** User starts `/predict`.
    3.  **Selection:** User selects 5 distinct players.
    4.  **Confirm:** User confirms selection.
    5.  **Verify:** Forecast is saved in DB.
*   **Test Case 4.3.2: Duplicate Player Prevention**
    1.  **Action:** User tries to select the same player twice.
    2.  **Expected:** Bot shows error/warning message.
*   **Test Case 4.3.3: Editing Prediction**
    1.  **Setup:** User has an existing forecast for an OPEN tournament.
    2.  **Action:** User chooses to edit the forecast.
    3.  **Verify:** Old forecast is removed/updated with new selection.
*   **Test Case 4.3.4: Predicting on Closed Tournament**
    1.  **Setup:** Tournament status is LIVE or FINISHED.
    2.  **Action:** User tries to predict.
    3.  **Expected:** Bot refuses access.

### 4.4 Analytics & Views
*   **Test Case 4.4.1: View Other Forecasts**
    1.  **Setup:** Multiple users have made forecasts.
    2.  **Action:** User requests "Analytics" for the tournament.
    3.  **Verify:** Summary stats (top picks) are calculated correctly.
