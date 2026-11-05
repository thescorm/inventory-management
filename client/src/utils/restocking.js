// Weights applied to a shortfall ratio so that items with rising demand are
// restocked before stable ones, and falling-demand items come last.
const TREND_WEIGHTS = {
  increasing: 1.25,
  stable: 1.0,
  decreasing: 0.75
}

// Units still missing to cover the forecast: forecasted demand minus what is on hand.
export function getShortfall(forecast) {
  return Math.max(0, forecast.forecasted_demand - forecast.quantity_on_hand)
}

// Total cost of covering every shortfall. Used to size the budget slider.
export function getFullRestockCost(forecasts) {
  return forecasts.reduce((sum, f) => sum + getShortfall(f) * f.unit_cost, 0)
}

/**
 * Recommend what to restock for a given budget.
 *
 * Urgency is the share of forecasted demand that is not covered by stock,
 * scaled by a trend weight. Items are filled most-urgent first, up to their
 * shortfall, until the budget runs out.
 *
 * An item that does not fit in full is bought partially. An item that cannot
 * afford even one unit is skipped rather than ending the loop, so the leftover
 * budget can still go to cheaper, less urgent items.
 *
 * Returns [{ forecast, shortfall, quantity }] ordered by urgency.
 */
export function recommendRestock(forecasts, budget) {
  const ranked = forecasts
    .map(forecast => {
      const shortfall = getShortfall(forecast)
      const coverageGap = forecast.forecasted_demand > 0 ? shortfall / forecast.forecasted_demand : 0
      const weight = TREND_WEIGHTS[forecast.trend] ?? 1.0
      return { forecast, shortfall, urgency: coverageGap * weight }
    })
    .filter(entry => entry.shortfall > 0)
    .sort((a, b) => b.urgency - a.urgency)

  let remaining = budget
  const recommendations = []

  for (const { forecast, shortfall } of ranked) {
    // Small epsilon: subtracting costs leaves float residue, so an exact fit
    // such as 99.99999999999999 would otherwise floor to one unit too few.
    const affordable = Math.floor(remaining / forecast.unit_cost + 1e-9)
    const quantity = Math.min(shortfall, affordable)
    if (quantity <= 0) continue

    recommendations.push({ forecast, shortfall, quantity })
    remaining -= quantity * forecast.unit_cost
  }

  return recommendations
}
