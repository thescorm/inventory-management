<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget.title') }}</h3>
        </div>
        <div class="budget-body">
          <label for="restocking-budget" class="budget-label">{{ t('restocking.budget.label') }}</label>
          <div class="budget-value" aria-live="polite">{{ money(budget) }}</div>
          <input
            id="restocking-budget"
            class="budget-slider"
            type="range"
            min="0"
            :max="maxBudget"
            step="500"
            v-model.number="budget"
            :style="{ '--fill': fillPercent + '%' }"
          />
          <div class="budget-range">
            <span>{{ money(0) }}</span>
            <span>{{ money(maxBudget) }}</span>
          </div>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.stats.budget') }}</div>
          <div class="stat-value">{{ money(budget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.stats.selectedTotal') }}</div>
          <div class="stat-value">{{ moneyPrecise(selectedTotal) }}</div>
        </div>
        <div :class="['stat-card', remaining < 0 ? 'danger' : 'success']">
          <div class="stat-label">{{ t('restocking.stats.remaining') }}</div>
          <div class="stat-value">{{ moneyPrecise(remaining) }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.stats.leadTime') }}</div>
          <div class="stat-value">{{ leadTimeDisplay }}</div>
        </div>
      </div>

      <div v-if="successOrder" class="success-banner" role="status">
        <span>{{ t('restocking.success', { orderNumber: successOrder.order_number, days: successOrder.lead_time_days }) }}</span>
        <router-link to="/orders" class="success-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error" role="alert">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ rows.length }})</h3>
        </div>

        <div v-if="rows.length === 0" class="empty-state">{{ t('restocking.noRecommendations') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th class="col-select">{{ t('restocking.table.select') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.onHand') }}</th>
                <th class="num">{{ t('restocking.table.forecast') }}</th>
                <th class="num">{{ t('restocking.table.shortfall') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
                <th>{{ t('restocking.table.supplier') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.sku" :class="{ 'row-unselected': !row.selected }">
                <td class="col-select">
                  <input
                    type="checkbox"
                    v-model="row.selected"
                    :aria-label="t('restocking.table.select') + ' ' + row.sku"
                  />
                </td>
                <td><strong>{{ row.sku }}</strong></td>
                <td>{{ translateProductName(row.forecast.item_name) }}</td>
                <td>
                  <span :class="['badge', row.forecast.trend]">
                    {{ t('trends.' + row.forecast.trend) }}
                  </span>
                </td>
                <td class="num">{{ row.forecast.quantity_on_hand }}</td>
                <td class="num">{{ row.forecast.forecasted_demand }}</td>
                <td class="num">{{ row.shortfall }}</td>
                <td class="num">{{ moneyPrecise(row.forecast.unit_cost) }}</td>
                <td class="num">
                  <input
                    class="qty-input"
                    type="number"
                    min="1"
                    :max="row.shortfall"
                    step="1"
                    v-model.number="row.quantity"
                    @change="clampQuantity(row)"
                    :aria-label="t('restocking.table.quantity') + ' ' + row.sku"
                  />
                </td>
                <td class="num"><strong>{{ moneyPrecise(lineCost(row)) }}</strong></td>
                <td>{{ t('restocking.days', { count: row.forecast.lead_time_days }) }}</td>
                <td>{{ row.forecast.supplier_name }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="order-actions">
          <button
            type="button"
            class="place-order-button"
            :disabled="!canPlace"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
          <span v-if="hintText" class="order-hint">{{ hintText }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'
import { recommendRestock, getFullRestockCost } from '../utils/restocking'

const BUDGET_STEP = 500

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])

    // Budget is always held in USD; conversion happens only at display time.
    const budget = ref(0)
    const rows = ref([])

    const submitting = ref(false)
    const successOrder = ref(null)
    const submitError = ref(null)

    // Round the full restock cost up to the next 1000 so the slider's top end
    // always covers every shortfall (rounding down would make it unreachable).
    const maxBudget = computed(() => {
      const fullCost = getFullRestockCost(forecasts.value)
      return Math.max(1000, Math.ceil(fullCost / 1000) * 1000)
    })

    // Percentage of the track to paint in the "filled" colour.
    const fillPercent = computed(() => {
      if (maxBudget.value <= 0) return 0
      return Math.min(100, Math.max(0, (budget.value / maxBudget.value) * 100))
    })

    // Display helpers. Negative amounts are formatted as "-<amount>" so the sign
    // sits in front of the currency symbol.
    const money = (amount) => {
      return amount < 0
        ? '-' + formatCurrency(-amount, currentCurrency.value)
        : formatCurrency(amount, currentCurrency.value)
    }
    const moneyPrecise = (amount) => {
      return amount < 0
        ? '-' + formatCurrencyWithDecimals(-amount, currentCurrency.value, 2)
        : formatCurrencyWithDecimals(amount, currentCurrency.value, 2)
    }

    // The quantity input can be transiently empty/NaN while the user types,
    // so every calculation goes through this guard.
    const safeQuantity = (row) => {
      const q = Number(row.quantity)
      return Number.isFinite(q) && q > 0 ? q : 0
    }
    const lineCost = (row) => safeQuantity(row) * row.forecast.unit_cost

    const rebuildRows = () => {
      rows.value = recommendRestock(forecasts.value, budget.value).map(rec => ({
        sku: rec.forecast.item_sku,
        forecast: rec.forecast,
        shortfall: rec.shortfall,
        selected: true,
        quantity: rec.quantity
      }))
    }

    // Moving the slider intentionally discards manual edits (unchecked rows and
    // custom quantities): the recommendation is recomputed for the new budget.
    watch(budget, rebuildRows)

    // Keep the entered quantity within 1..shortfall once the user commits it.
    const clampQuantity = (row) => {
      const q = Math.floor(Number(row.quantity))
      if (!Number.isFinite(q)) {
        row.quantity = 1
        return
      }
      row.quantity = Math.min(Math.max(q, 1), row.shortfall)
    }

    const selectedRows = computed(() => rows.value.filter(r => r.selected && safeQuantity(r) > 0))

    const selectedTotal = computed(() => {
      return selectedRows.value.reduce((sum, r) => sum + lineCost(r), 0)
    })

    // Rounded to cents so float noise (e.g. -1e-13 on an order that lands exactly
    // on budget) cannot turn the card red and show "-$0.00".
    const remaining = computed(() => Math.round((budget.value - selectedTotal.value) * 100) / 100)

    // The order is as slow as its slowest supplier.
    const leadTimeDays = computed(() => {
      if (selectedRows.value.length === 0) return null
      return Math.max(...selectedRows.value.map(r => r.forecast.lead_time_days))
    })

    const leadTimeDisplay = computed(() => {
      return leadTimeDays.value === null
        ? '–' // en dash when nothing is selected
        : t('restocking.days', { count: leadTimeDays.value })
    })

    // The server compares the total to the budget at cent precision, so round
    // here too; otherwise float noise (e.g. 1000.0000000001) would disable the
    // button for an order the server would accept.
    const roundedTotal = computed(() => Math.round(selectedTotal.value * 100) / 100)

    const canPlace = computed(() => {
      return selectedRows.value.length > 0 &&
        roundedTotal.value <= budget.value &&
        !submitting.value
    })

    const hintText = computed(() => {
      if (selectedRows.value.length === 0) return t('restocking.nothingSelected')
      if (roundedTotal.value > budget.value) return t('restocking.overBudget')
      return ''
    })

    // FastAPI returns `detail` as a string for 400/404 but as an array of
    // objects for 422 validation errors; flatten the latter into readable text.
    const formatErrorDetail = (err) => {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        return detail.map(d => d.msg).join('; ')
      }
      return detail || err.message
    }

    const placeOrder = async () => {
      if (!canPlace.value) return
      // Clear the previous outcome so stale banners never sit next to a new result.
      successOrder.value = null
      submitError.value = null
      submitting.value = true
      try {
        successOrder.value = await api.createRestockingOrder({
          items: selectedRows.value.map(r => ({
            item_sku: r.sku,
            // The server expects an integer; a typed fraction could otherwise slip through.
            quantity: Math.max(1, Math.floor(safeQuantity(r)))
          })),
          budget: budget.value
        })
        // Untick everything so a second click cannot silently place a duplicate
        // order; the user can tick items again to order more.
        rows.value.forEach(r => { r.selected = false })
      } catch (err) {
        submitError.value = t('restocking.failed', {
          message: formatErrorDetail(err)
        })
      } finally {
        submitting.value = false
      }
    }

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        const data = await api.getDemandForecasts()
        // Items without a unit cost cannot be priced, so they are not restockable.
        forecasts.value = data.filter(f => f.unit_cost !== null && f.unit_cost !== undefined)

        // Start at roughly half the maximum, snapped to the slider step.
        const initial = Math.round(maxBudget.value / 2 / BUDGET_STEP) * BUDGET_STEP
        budget.value = Math.min(initial, maxBudget.value)
        // The budget watcher does not fire if the value is unchanged, so build explicitly.
        rebuildRows()
      } catch (err) {
        error.value = 'Failed to load demand forecasts: ' + err.message
      } finally {
        loading.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      currentCurrency,
      translateProductName,
      loading,
      error,
      budget,
      maxBudget,
      fillPercent,
      rows,
      submitting,
      successOrder,
      submitError,
      money,
      moneyPrecise,
      lineCost,
      clampQuantity,
      selectedTotal,
      remaining,
      leadTimeDisplay,
      canPlace,
      hintText,
      placeOrder
    }
  }
}
</script>

<style scoped>
/* Budget card */
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-body {
  display: grid;
  gap: 0.75rem;
  padding: 0;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 2.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.budget-range {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
}

/* Slider: --fill is set inline and paints the filled part of the track */
.budget-slider {
  --fill: 0%;
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(to right, #3b82f6 var(--fill), #e2e8f0 var(--fill));
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-runnable-track {
  height: 8px;
  border-radius: 999px;
  background: transparent;
}

.budget-slider::-moz-range-track {
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
}

.budget-slider::-moz-range-progress {
  height: 8px;
  border-radius: 999px;
  background: #3b82f6;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 22px;
  height: 22px;
  margin-top: -7px; /* centre the thumb on the 8px track */
  border-radius: 50%;
  background: white;
  border: 2px solid #3b82f6;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.2);
  transition: box-shadow 0.15s ease;
}

.budget-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: white;
  border: 2px solid #3b82f6;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.2);
}

.budget-slider:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
}

.budget-slider:focus-visible::-moz-range-thumb {
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
}

/* Result banners */
.success-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
}

.success-link {
  color: #166534;
  font-weight: 600;
  text-decoration: underline;
}

.success-link:hover {
  color: #14532d;
}

/* Table */
.empty-state {
  padding: 2rem 0;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

th.num,
td.num {
  text-align: right;
  white-space: nowrap;
}

.col-select {
  width: 64px;
  text-align: center;
}

.row-unselected td {
  color: #94a3b8;
}

.qty-input {
  width: 80px;
  padding: 0.25rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.875rem;
  color: #0f172a;
  background: white;
  text-align: right;
}

.qty-input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

/* Place order */
.order-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  padding: 1rem 0 0;
}

.place-order-button {
  padding: 0.625rem 1.5rem;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  background: #3b82f6;
  color: white;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.place-order-button:hover:not(:disabled) {
  background: #2563eb;
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
}

.place-order-button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.35);
}

.place-order-button:disabled {
  background: #cbd5e1;
  color: #64748b;
  cursor: not-allowed;
}

.order-hint {
  font-size: 0.875rem;
  color: #64748b;
}

@media (max-width: 640px) {
  .budget-value {
    font-size: 1.75rem;
  }
}
</style>
