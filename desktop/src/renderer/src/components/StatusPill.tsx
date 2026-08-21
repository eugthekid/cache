/**
 * One place mapping every status word in the app to a pill color -- so
 * "what color is 'cancelled'" is answered once, not re-decided per screen.
 */
const PILL_CLASS: Record<string, string> = {
  success: 'pill-success',
  delivered: 'pill-success',
  sold: 'pill-success',
  failed: 'pill-failed',
  cancelled: 'pill-failed',
  exception: 'pill-failed',
  returned: 'pill-failed',
  lost: 'pill-failed',
  listed: 'pill-warn',
  label_created: 'pill-warn',
  in_transit: 'pill-warn',
  pending: 'pill-neutral',
  in_hand: 'pill-neutral',
  not_shipped: 'pill-neutral'
}

interface StatusPillProps {
  status: string
  label?: string
}

function StatusPill({ status, label }: StatusPillProps): React.JSX.Element {
  const className = PILL_CLASS[status] ?? 'pill-neutral'
  const text = label ?? status.replace(/_/g, ' ')
  return (
    <span className={`pill ${className}`}>
      <span className="dot" />
      {text}
    </span>
  )
}

export default StatusPill
