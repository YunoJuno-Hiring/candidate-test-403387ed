import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { runBilling, fetchInvoices } from '../api/billing'
import { ApiError } from '../api/client'

// Only months that have ended can be billed, so default to last month.
function previousMonth() {
  const now = new Date()
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`
}

function runErrorMessage(error: Error) {
  if (error instanceof ApiError) {
    const message = error.data.month ?? error.data.detail
    if (typeof message === 'string') return message
  }
  return 'Billing run failed. Please try again.'
}

export default function Billing() {
  const [month, setMonth] = useState(previousMonth)
  const [runResult, setRunResult] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  const invoicesQuery = useQuery({
    queryKey: ['invoices', month],
    queryFn: () => fetchInvoices(month),
  })

  const billingMutation = useMutation({
    mutationFn: () => runBilling(month),
    onSuccess: (data) => {
      setRunResult(
        `Billing run complete — ${data.invoices_generated} invoice(s) generated.`
      )
      setRunError(null)
      invoicesQuery.refetch()
    },
    onError: (error) => {
      setRunError(runErrorMessage(error))
      setRunResult(null)
    },
  })

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 mb-1">Billing</h1>
        <p className="text-slate-500 text-sm">Generate monthly invoices from approved timesheet hours.</p>
      </div>

      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h2 className="text-base font-medium text-slate-800 mb-4">Run billing</h2>
        <div className="flex items-end gap-4">
          <div>
            <label htmlFor="month" className="block text-sm font-medium text-slate-700 mb-1">
              Billing month
            </label>
            <input
              id="month"
              type="month"
              value={month}
              onChange={(e) => {
                setMonth(e.target.value)
                setRunResult(null)
                setRunError(null)
              }}
              className="border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <button
            onClick={() => billingMutation.mutate()}
            disabled={billingMutation.isPending}
            className="bg-indigo-600 text-white text-sm px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {billingMutation.isPending ? 'Running…' : 'Run billing'}
          </button>
        </div>

        {runResult && (
          <div className="mt-4 bg-green-50 border border-green-200 text-green-800 text-sm rounded px-3 py-2">
            {runResult}
          </div>
        )}
        {runError && (
          <div className="mt-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded px-3 py-2">
            {runError}
          </div>
        )}
      </div>

      <div>
        <h2 className="text-base font-medium text-slate-800 mb-3">
          Invoices for {month}
        </h2>

        {invoicesQuery.isLoading ? (
          <p className="text-slate-500 text-sm">Loading invoices…</p>
        ) : invoicesQuery.isError ? (
          <p className="text-red-600 text-sm">Failed to load invoices.</p>
        ) : !invoicesQuery.data || invoicesQuery.data.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-lg px-6 py-10 text-center">
            <p className="text-slate-500 text-sm">No invoices for this month.</p>
            <p className="text-slate-400 text-xs mt-1">
              Run billing to generate invoices from approved timesheet entries.
            </p>
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-slate-600">Invoice ID</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {invoicesQuery.data.map((inv) => (
                  <tr key={String(inv.id)}>
                    <td className="px-4 py-3 text-slate-700">{String(inv.id)}</td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        to={`/billing/invoices/${String(inv.id)}`}
                        className="text-indigo-600 hover:text-indigo-800 font-medium"
                      >
                        View →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
