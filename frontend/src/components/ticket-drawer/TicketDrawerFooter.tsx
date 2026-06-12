import { InformationCircleIcon, NoSymbolIcon, TrashIcon } from '@heroicons/react/24/outline'

interface TicketDrawerFooterProps {
  deleting: boolean
  spamming: boolean
  onDelete: () => void
  onSpam: () => void
}

export function TicketDrawerFooter({
  deleting,
  spamming,
  onDelete,
  onSpam,
}: TicketDrawerFooterProps) {
  return (
    <div className="px-6 py-4 border-t border-app-border shrink-0 space-y-3">
      <div className="flex items-start gap-2 text-xs text-app-nav-text">
        <InformationCircleIcon className="w-3.5 h-3.5 shrink-0 mt-0.5" />
        <p>
          <span className="font-medium text-slate-950">Delete</span> removes this ticket from Korca — it's re-imported the next time it's updated in Teamwork.{' '}
          <span className="font-medium text-slate-950">Spam</span> removes it and blocks it from ever being re-imported.
          <br />Korca <span className="font-bold text-slate-950">never</span> deletes tickets from Teamwork Desk.
        </p>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onSpam}
          disabled={deleting || spamming}
          className="flex-1 inline-flex items-center justify-center gap-1.5 px-4 py-2 text-sm font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <NoSymbolIcon className="w-3.5 h-3.5" />
          {spamming ? 'Blocking...' : 'Spam'}
        </button>
        <button
          onClick={onDelete}
          disabled={deleting || spamming}
          className="flex-1 inline-flex items-center justify-center gap-1.5 px-4 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <TrashIcon className="w-3.5 h-3.5" />
          {deleting ? 'Deleting...' : 'Delete'}
        </button>
      </div>
    </div>
  )
}
