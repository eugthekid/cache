interface EmptyStateProps {
  icon: React.ReactNode
  iconBg: string
  iconBorder?: string
  title: string
  body: string
  actions?: React.ReactNode
}

/** The in-card "nothing here" pattern from the design canvas -- an icon
 * shell, a headline, a line of body copy, and optional action buttons.
 * Used both for true empty states and for filtered-to-nothing states
 * (see ORDERS_FILTER_EMPTY-style usage in screens). */
function EmptyState({ icon, iconBg, iconBorder, title, body, actions }: EmptyStateProps): React.JSX.Element {
  return (
    <div className="emptybox">
      <div className="icon-shell" style={{ background: iconBg, borderColor: iconBorder }}>
        {icon}
      </div>
      <div className="emptybox-title">{title}</div>
      <div className="emptybox-body">{body}</div>
      {actions && <div style={{ display: 'flex', gap: 9, marginTop: 2, flexWrap: 'wrap', justifyContent: 'center' }}>{actions}</div>}
    </div>
  )
}

export default EmptyState
