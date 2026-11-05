<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen && backlogItem" class="modal-overlay" @click="close">
        <div class="modal-container" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">
              {{ mode === 'view' ? 'Purchase Order' : 'Create Purchase Order' }}
            </h3>
            <button class="close-button" type="button" aria-label="Close" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <!-- Backlog item context (shown in both modes) -->
            <div class="context-section">
              <div class="context-name">{{ translateProductName(backlogItem.item_name) }}</div>
              <div class="context-meta">
                <span class="mono">SKU: {{ backlogItem.item_sku }}</span>
                <span class="mono">Order: {{ backlogItem.order_id }}</span>
                <span>Shortage: {{ shortage }} units</span>
              </div>
            </div>

            <!-- View mode -->
            <template v-if="mode === 'view'">
              <div v-if="viewLoading" class="state-message">Loading purchase order...</div>
              <div v-else-if="viewError" class="error-message">{{ viewError }}</div>
              <div v-else-if="purchaseOrder" class="info-grid">
                <div class="info-item">
                  <div class="info-label">PO Number</div>
                  <div class="info-value mono">{{ purchaseOrder.id }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Status</div>
                  <div class="info-value">
                    <span class="badge info">{{ purchaseOrder.status || 'N/A' }}</span>
                  </div>
                </div>
                <div class="info-item">
                  <div class="info-label">Supplier</div>
                  <div class="info-value">{{ purchaseOrder.supplier_name }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Expected Delivery</div>
                  <div class="info-value">{{ formatDate(purchaseOrder.expected_delivery_date) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Quantity</div>
                  <div class="info-value">{{ purchaseOrder.quantity }} units</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Unit Cost</div>
                  <div class="info-value">{{ formatMoney(purchaseOrder.unit_cost) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Total</div>
                  <div class="info-value strong">{{ formatMoney(purchaseOrder.quantity * purchaseOrder.unit_cost) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Created</div>
                  <div class="info-value">{{ formatDate(purchaseOrder.created_date) }}</div>
                </div>
                <div class="info-item full-width">
                  <div class="info-label">Notes</div>
                  <div class="info-value notes">{{ purchaseOrder.notes || 'None' }}</div>
                </div>
              </div>
            </template>

            <!-- Create mode -->
            <form v-else id="po-form" class="po-form" novalidate @submit.prevent="submit">
              <div class="form-field">
                <label for="po-supplier">Supplier</label>
                <input
                  id="po-supplier"
                  v-model="form.supplier_name"
                  type="text"
                  :class="{ invalid: errors.supplier_name }"
                  :disabled="saving"
                />
                <div v-if="errors.supplier_name" class="field-error">{{ errors.supplier_name }}</div>
              </div>

              <div class="form-row">
                <div class="form-field">
                  <label for="po-quantity">Quantity</label>
                  <input
                    id="po-quantity"
                    v-model.number="form.quantity"
                    type="number"
                    min="1"
                    step="1"
                    :class="{ invalid: errors.quantity }"
                    :disabled="saving"
                  />
                  <div v-if="errors.quantity" class="field-error">{{ errors.quantity }}</div>
                </div>

                <div class="form-field">
                  <label for="po-unit-cost">Unit Cost (USD)</label>
                  <input
                    id="po-unit-cost"
                    v-model.number="form.unit_cost"
                    type="number"
                    min="0.01"
                    step="0.01"
                    :class="{ invalid: errors.unit_cost }"
                    :disabled="saving"
                  />
                  <div v-if="errors.unit_cost" class="field-error">{{ errors.unit_cost }}</div>
                </div>
              </div>

              <div class="form-field">
                <label for="po-delivery">Expected Delivery Date</label>
                <input
                  id="po-delivery"
                  v-model="form.expected_delivery_date"
                  type="date"
                  :min="today"
                  :class="{ invalid: errors.expected_delivery_date }"
                  :disabled="saving"
                />
                <div v-if="errors.expected_delivery_date" class="field-error">{{ errors.expected_delivery_date }}</div>
              </div>

              <div class="form-field">
                <label for="po-notes">Notes (optional)</label>
                <textarea id="po-notes" v-model="form.notes" rows="3" :disabled="saving"></textarea>
              </div>

              <div class="total-row">
                <span class="info-label">Total</span>
                <span class="total-value">{{ formatMoney(total) }}</span>
              </div>

              <div v-if="submitError" class="error-message">{{ submitError }}</div>
            </form>
          </div>

          <div class="modal-footer">
            <button class="btn-secondary" type="button" @click="close">
              {{ mode === 'view' ? 'Close' : 'Cancel' }}
            </button>
            <button
              v-if="mode !== 'view'"
              class="btn-primary"
              type="submit"
              form="po-form"
              :disabled="saving"
            >
              {{ saving ? 'Saving...' : 'Create Purchase Order' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const { translateProductName } = useI18n()

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  backlogItem: {
    type: Object,
    default: null
  },
  mode: {
    type: String,
    default: 'create',
    validator: (value) => ['create', 'view'].includes(value)
  }
})

const emit = defineEmits(['close', 'po-created'])

const form = ref({
  supplier_name: '',
  quantity: 1,
  unit_cost: null,
  expected_delivery_date: '',
  notes: ''
})
const errors = ref({})
const saving = ref(false)
const submitError = ref(null)

const purchaseOrder = ref(null)
const viewLoading = ref(false)
const viewError = ref(null)

const shortage = computed(() => {
  if (!props.backlogItem) return 0
  return Math.max(0, props.backlogItem.quantity_needed - props.backlogItem.quantity_available)
})

// Local-calendar "today" as YYYY-MM-DD. toISOString() would use UTC and can be off by one day.
const todayString = () => {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}
const today = ref(todayString())

const total = computed(() => {
  const qty = Number(form.value.quantity)
  const cost = Number(form.value.unit_cost)
  if (!Number.isFinite(qty) || !Number.isFinite(cost)) return 0
  return qty * cost
})

const resetForm = () => {
  today.value = todayString()
  form.value = {
    supplier_name: '',
    // Default to the shortage, but never below the minimum of 1
    quantity: Math.max(1, shortage.value),
    unit_cost: null,
    expected_delivery_date: '',
    notes: ''
  }
  errors.value = {}
  saving.value = false
  submitError.value = null
}

const loadPurchaseOrder = async () => {
  purchaseOrder.value = null
  viewError.value = null
  viewLoading.value = true
  try {
    purchaseOrder.value = await api.getPurchaseOrderByBacklogItem(props.backlogItem.id)
  } catch (err) {
    console.error('Failed to load purchase order:', err)
    viewError.value = err.response?.status === 404
      ? 'No purchase order exists for this item.'
      : 'Failed to load purchase order.'
  } finally {
    viewLoading.value = false
  }
}

// Re-initialise every time the modal opens (or is reused for another item/mode)
watch(
  () => [props.isOpen, props.mode, props.backlogItem?.id],
  () => {
    if (!props.isOpen || !props.backlogItem) return
    if (props.mode === 'view') {
      loadPurchaseOrder()
    } else {
      resetForm()
    }
  },
  { immediate: true }
)

const validate = () => {
  const result = {}
  const f = form.value

  if (!f.supplier_name || !f.supplier_name.trim()) {
    result.supplier_name = 'Supplier is required.'
  }

  const qty = Number(f.quantity)
  if (!Number.isInteger(qty) || qty < 1) {
    result.quantity = 'Quantity must be a whole number of at least 1.'
  }

  const cost = Number(f.unit_cost)
  if (f.unit_cost === null || f.unit_cost === '' || !Number.isFinite(cost) || cost <= 0) {
    result.unit_cost = 'Unit cost must be greater than 0.'
  }

  if (!f.expected_delivery_date) {
    result.expected_delivery_date = 'Expected delivery date is required.'
  } else if (isNaN(new Date(f.expected_delivery_date).getTime())) {
    result.expected_delivery_date = 'Enter a valid date.'
  } else if (f.expected_delivery_date < today.value) {
    // Both values are YYYY-MM-DD, so string comparison is chronological
    result.expected_delivery_date = 'Delivery date cannot be in the past.'
  }

  errors.value = result
  return Object.keys(result).length === 0
}

const extractErrorMessage = (err) => {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  // FastAPI validation errors arrive as an array of { msg }
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ')
  return 'Failed to create purchase order.'
}

const submit = async () => {
  if (saving.value || !validate()) return

  saving.value = true
  submitError.value = null
  try {
    const f = form.value
    const po = await api.createPurchaseOrder({
      backlog_item_id: props.backlogItem.id,
      supplier_name: f.supplier_name.trim(),
      quantity: Number(f.quantity),
      unit_cost: Number(f.unit_cost),
      expected_delivery_date: f.expected_delivery_date,
      // Empty string (not null) so it validates whether the backend field is `str = ""` or Optional[str]
      notes: f.notes.trim()
    })
    emit('po-created', po)
  } catch (err) {
    console.error('Failed to create purchase order:', err)
    submitError.value = extractErrorMessage(err)
  } finally {
    saving.value = false
  }
}

const close = () => {
  emit('close')
}

const formatMoney = (value) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return 'N/A'
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  // Date-only strings parse as UTC; pin to local midnight so the displayed day does not shift
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(dateString) ? `${dateString}T00:00:00` : dateString)
  if (isNaN(date.getTime())) return 'N/A'
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  })
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 1rem;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15);
  max-width: 640px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
}

.context-section {
  padding-bottom: 1.25rem;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.context-name {
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 0.5rem;
}

.context-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.25rem;
  font-size: 0.875rem;
  color: #64748b;
}

.mono {
  font-family: 'Monaco', 'Courier New', monospace;
}

.state-message {
  padding: 1.5rem 0;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.error-message {
  padding: 0.75rem 1rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 0.875rem;
}

/* Read-only view */
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.info-item.full-width {
  grid-column: 1 / -1;
}

.info-label {
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.info-value {
  font-size: 0.938rem;
  color: #0f172a;
  font-weight: 500;
}

.info-value.strong {
  font-weight: 700;
}

.info-value.notes {
  white-space: pre-wrap;
  font-weight: 400;
}

.badge.info {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 6px;
  background: #dbeafe;
  color: #1e40af;
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: capitalize;
}

/* Create form */
.po-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-width: 0;
}

.form-field label {
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.form-field input,
.form-field textarea {
  padding: 0.625rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.938rem;
  font-family: inherit;
  color: #0f172a;
  background: white;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.form-field textarea {
  resize: vertical;
}

.form-field input:focus,
.form-field textarea:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.form-field input:disabled,
.form-field textarea:disabled {
  background: #f8fafc;
  color: #94a3b8;
}

.form-field input.invalid {
  border-color: #ef4444;
}

.field-error {
  font-size: 0.813rem;
  color: #dc2626;
}

.total-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.total-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.modal-footer {
  padding: 1.5rem;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-secondary {
  padding: 0.625rem 1.25rem;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.875rem;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.btn-secondary:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.btn-primary {
  padding: 0.625rem 1.25rem;
  background: #0f172a;
  border: 1px solid #0f172a;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.875rem;
  color: white;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Modal transition animations */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.2s ease;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.95);
}

@media (max-width: 520px) {
  .form-row {
    grid-template-columns: 1fr;
  }
}
</style>
