import type { User } from '../../types'

export const DRAWER_INPUT_CLS =
  'w-full text-sm border border-app-border rounded-lg px-3 py-2 bg-app-bg text-slate-950 placeholder-app-nav-text focus:outline-none focus:ring-2 focus:ring-app-accent'

interface DrawerFormFieldProps {
  readonly id: string
  readonly label: string
  readonly type?: string
  readonly placeholder: string
  readonly value: string
  readonly onChange: (value: string) => void
}

export function DrawerFormField({ id, label, type = 'text', placeholder, value, onChange }: DrawerFormFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-app-nav-text mb-1">{label}</label>
      <input
        id={id}
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        className={DRAWER_INPUT_CLS}
      />
    </div>
  )
}

interface DrawerManagerSelectProps {
  readonly value: string
  readonly allUsers: User[]
  readonly excludeId?: string
  readonly onChange: (email: string) => void
}

export function DrawerManagerSelect({ value, allUsers, excludeId, onChange }: DrawerManagerSelectProps) {
  const options = excludeId ? allUsers.filter(u => u.id !== excludeId) : allUsers
  return (
    <div>
      <label htmlFor="manager_email" className="block text-xs text-app-nav-text mb-1">Manager</label>
      <select
        id="manager_email"
        value={value}
        onChange={e => onChange(e.target.value)}
        className={DRAWER_INPUT_CLS}
      >
        <option value="">— No manager —</option>
        {options.map(u => (
          <option key={u.email} value={u.email}>{u.name || u.email}</option>
        ))}
      </select>
    </div>
  )
}
