'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { getListings, getProfile, saveListing, unsaveListing } from '@/lib/api'

type Listing = {
  id: string
  address: string
  city: string
  county: string
  sale_date: string | null
  sale_time: string | null
  sale_location: string | null
  days_until_sale: number | null
  assessed_value: number | null
  rough_equity_est: number | null
  est_profit_potential: number | null
  lender: string | null
  trustee: string | null
  investment_priority: string | null
  stage: string | null
  is_new: boolean
}

function PriorityBadge({ priority }: { priority: string | null }) {
  const colors: Record<string, string> = {
    High:   'bg-red-100 text-red-700',
    Medium: 'bg-yellow-100 text-yellow-700',
    Low:    'bg-gray-100 text-gray-600',
  }
  if (!priority) return null
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${colors[priority] ?? 'bg-gray-100 text-gray-600'}`}>
      {priority}
    </span>
  )
}

function fmt(n: number | null) {
  if (!n) return '—'
  return '$' + n.toLocaleString()
}

export default function DashboardPage() {
  const router = useRouter()
  const [listings, setListings] = useState<Listing[]>([])
  const [profile, setProfile] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [saved, setSaved] = useState<Set<string>>(new Set())
  const [filterPriority, setFilterPriority] = useState('')
  const [filterCounty, setFilterCounty] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) router.push('/login')
    })
  }, [router])

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const [listData, prof] = await Promise.all([
          getListings({ priority: filterPriority || undefined, county: filterCounty || undefined, page }),
          getProfile(),
        ])
        setListings(listData.listings)
        setTotal(listData.total)
        setProfile(prof)
      } catch {
        router.push('/login')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [filterPriority, filterCounty, page, router])

  async function toggleSave(id: string) {
    if (saved.has(id)) {
      await unsaveListing(id)
      setSaved(prev => { const s = new Set(prev); s.delete(id); return s })
    } else {
      await saveListing(id)
      setSaved(prev => new Set(prev).add(id))
    }
  }

  const pageSize = 50
  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Foreclosure Finder</h1>
        <div className="flex items-center gap-4">
          {profile && (
            <span className="text-sm text-gray-500">
              {profile.counties?.length ?? 0} counties · <span className="capitalize">{profile.plan}</span>
            </span>
          )}
          <button onClick={() => router.push('/settings')} className="text-sm text-blue-600 hover:underline">Settings</button>
          <button onClick={async () => { await supabase.auth.signOut(); router.push('/login') }}
            className="text-sm text-gray-500 hover:text-gray-800">Sign out</button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-6">
          <select value={filterPriority} onChange={e => { setFilterPriority(e.target.value); setPage(1) }}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white">
            <option value="">All priorities</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Low">Low</option>
          </select>

          {profile?.counties?.length > 1 && (
            <select value={filterCounty} onChange={e => { setFilterCounty(e.target.value); setPage(1) }}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white">
              <option value="">All counties</option>
              {profile.counties.map((c: string) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}

          <span className="ml-auto text-sm text-gray-500 self-center">{total} listings</span>
        </div>

        {/* Listings */}
        {loading ? (
          <div className="text-center py-20 text-gray-400">Loading...</div>
        ) : listings.length === 0 ? (
          <div className="text-center py-20 text-gray-400">
            <p className="text-lg font-medium mb-2">No listings yet</p>
            <p className="text-sm">Select counties in <button onClick={() => router.push('/settings')} className="text-blue-600 underline">Settings</button> to see leads</p>
          </div>
        ) : (
          <div className="space-y-3">
            {listings.map(l => (
              <div key={l.id} className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-sm transition-shadow">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      {l.is_new && <span className="text-xs bg-blue-500 text-white px-2 py-0.5 rounded-full font-semibold">NEW</span>}
                      <PriorityBadge priority={l.investment_priority} />
                      <span className="text-xs text-gray-400">{l.county}</span>
                    </div>
                    <p className="font-semibold text-gray-900 truncate">{l.address}</p>
                    <p className="text-sm text-gray-500">{l.city}</p>
                  </div>
                  <button onClick={() => toggleSave(l.id)} className="text-gray-300 hover:text-yellow-400 text-xl flex-shrink-0">
                    {saved.has(l.id) ? '★' : '☆'}
                  </button>
                </div>

                <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  <div>
                    <p className="text-gray-400 text-xs">Sale date</p>
                    <p className="font-medium">{l.sale_date ?? '—'}</p>
                    <p className="text-xs text-gray-400">{l.sale_time ?? ''}</p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs">Days until sale</p>
                    <p className={`font-medium ${(l.days_until_sale ?? 99) <= 14 ? 'text-red-600' : ''}`}>
                      {l.days_until_sale != null ? `${l.days_until_sale}d` : '—'}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs">Est. value</p>
                    <p className="font-medium">{fmt(l.assessed_value)}</p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs">Est. profit (70% rule)</p>
                    <p className={`font-medium ${(l.est_profit_potential ?? 0) > 0 ? 'text-green-600' : 'text-gray-400'}`}>
                      {fmt(l.est_profit_potential)}
                    </p>
                  </div>
                </div>

                {(l.lender || l.trustee) && (
                  <div className="mt-3 text-xs text-gray-400">
                    {l.lender && <span>Lender: {l.lender}</span>}
                    {l.lender && l.trustee && <span className="mx-2">·</span>}
                    {l.trustee && <span>Trustee: {l.trustee}</span>}
                  </div>
                )}

                <div className="mt-3">
                  <button onClick={() => router.push(`/listings/${l.id}`)}
                    className="text-sm text-blue-600 hover:underline">View details →</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex justify-center gap-2 mt-8">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
              className="px-4 py-2 border rounded-lg text-sm disabled:opacity-40">← Prev</button>
            <span className="px-4 py-2 text-sm text-gray-500">Page {page} of {totalPages}</span>
            <button disabled={page === totalPages} onClick={() => setPage(p => p + 1)}
              className="px-4 py-2 border rounded-lg text-sm disabled:opacity-40">Next →</button>
          </div>
        )}
      </main>
    </div>
  )
}
