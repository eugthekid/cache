import { useEffect, useRef } from 'react'
import { api, type Order } from '../api/client'

// Matches the email poller's own cadence (backend/app/email_poller.py,
// POLL_SECONDS = 120) -- a new shipping alert can only ever appear right
// after a poll cycle lands, so checking faster than that just burns a
// request for nothing new.
const CHECK_INTERVAL_MS = 120_000

function notificationBody(order: Order): string {
  const name = order.product_name ?? order.raw_product_text ?? 'An order'
  return order.shipping_status === 'delivered' ? `${name} was delivered.` : `${name} hit a shipping exception.`
}

/**
 * OS-level desktop notification for a NEWLY-entered shipping_alert_at --
 * separate from Orders.tsx's in-app banner (which already existed and
 * still owns "seen"/dismiss state; this hook never acks anything, it
 * only ever reads the unseen list to find what's new since last check).
 *
 * Runs from App.tsx, not Orders.tsx, so a delivery notification still
 * fires while the user is looking at Dashboard or Inventory -- the whole
 * point of an OS notification over an in-app banner is not depending on
 * which screen happens to be open.
 */
function useShippingNotifications(enabled: boolean): void {
  // IDs already notified about, so a later poll (or the in-app banner's
  // own separate ack) never re-notifies for the same alert. Not
  // persisted across app restarts on purpose: shipping_alert_seen_at is
  // the durable "have I dealt with this" record; this ref only prevents
  // duplicate OS notifications within one running session.
  const notified = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!enabled) return
    if (typeof Notification === 'undefined') return

    if (Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }

    let cancelled = false

    async function check(): Promise<void> {
      if (Notification.permission !== 'granted') return
      try {
        const alerts = await api.orders.shippingAlerts()
        if (cancelled) return
        for (const order of alerts) {
          if (notified.current.has(order.id)) continue
          notified.current.add(order.id)
          new Notification(order.shipping_status === 'delivered' ? 'Package delivered' : 'Shipping exception', {
            body: notificationBody(order)
          })
        }
      } catch {
        // A failed check should never surface to the user -- there's
        // nothing actionable here, just try again next interval.
      }
    }

    check()
    const timer = window.setInterval(check, CHECK_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [enabled])
}

export default useShippingNotifications
