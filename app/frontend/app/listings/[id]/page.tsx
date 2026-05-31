'use client'
import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { getListing, saveListing, unsaveListing } from '@/lib/api'

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (!value) return null
  return (
    <div className="flex justify-between py-2 border-b border-gray-100 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900 text-right max-w-xs">{String(value)}</span>
    </div>
  )
}

function fmt(n: number | null) {
  if (!n) return null
  return '$' + n.toLocaleString()
}

export default function ListingDetailPage() {
  const router = useRouter()
  const params = useParams()
  const id = params.id as string
  const [listing, setListing] = useState<any>(null)
  const [isSaved, setIsSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getListing(id).then(setListing).catch(() => router.push('/dashboard')).finally(() => setLoading(false))
  }, [id, router])

  async function toggleSave() {
    if (isSaved) { await unsaveListing(id); setIsSaved(false) }
    else { await saveListing(id); setIsSaved(true) }
  }

  if (loading) return <div className="min-h-screen flex items-center justify-center text-gray-400">Loading...</div>
  if (!listing) return null

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button onClick={() => router.push('/dashboard')} className="text-blue-600 hover:underline text-sm">← Back</button>
        <h1 className="text-lg font-semibold text-gray-900 truncate flex-1">{listing.address}</h1>
        <button onClick={toggleSave} className="text-2xl text-gray-300 hover:text-yellow-400">
          {isSaved ? '★' : '☆'}
        </button>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        {/* Hero card */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-start justify-between mb-4">
            <div>
              <p className="text-xl font-bold text-gray-900">{listing.address}</p>
              <p className="text-gray-500">{listing.city}, VA {listing.zip} · {listing.county}</p>
            </div>
            {listing.investment_priority && (
              <span className={`text-sm font-semibold px-3 py-1 rounded-full ${
                listing.investment_priority === 'High' ? 'bg-red-100 text-red-700' :
                listing.investment_priority === 'Medium' ? 'bg-yellow-100 text-yellow-700' :
                'bg-gray-100 text-gray-600'
              }`}>{listing.investment_priority} Priority</span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'Sale date', value: listing.sale_date },
              { label: 'Sale time', value: listing.sale_time },
              { label: 'Days until sale', value: listing.days_until_sale != null ? `${listing.days_until_sale} days` : null },
              { label: 'Est. value', value: fmt(listing.assessed_value) },
              { label: 'Est. equity', value: fmt(listing.rough_equity_est) },
              { label: 'Est. profit (70%)', value: fmt(listing.est_profit_potential) },
            ].map(({ label, value }) => value ? (
              <div key={label} className="bg-gray-50 rounded-lg p-3">
                <p className="text-xs text-gray-400 mb-1">{label}</p>
                <p className="font-semibold text-gray-900">{value}</p>
              </div>
            ) : null)}
          </div>
        </div>

        {/* Property details */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold text-gray-900 mb-3">Property details</h2>
          <Row label="Type" value={listing.property_type} />
          <Row label="Beds / Baths / Sqft" value={listing.beds_baths_sqft} />
          <Row label="Year built" value={listing.year_built} />
          <Row label="Lot size" value={listing.lot_size} />
          <Row label="Last sold" value={listing.last_sold_date} />
          <Row label="Last sold price" value={fmt(listing.last_sold_price)} />
          <Row label="Years since last sale" value={listing.years_since_last_sale} />
        </div>

        {/* Owner info */}
        {(listing.owner_name || listing.owner_mailing_address) && (
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="font-semibold text-gray-900 mb-3">Owner info</h2>
            <Row label="Owner" value={listing.owner_name} />
            <Row label="Mailing address" value={listing.owner_mailing_address} />
            <Row label="Mailing differs" value={listing.owner_mailing_differs ? 'Yes — owner is not at property' : null} />
          </div>
        )}

        {/* Sale info */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold text-gray-900 mb-3">Sale details</h2>
          <Row label="Location" value={listing.sale_location} />
          <Row label="Lender" value={listing.lender} />
          <Row label="Trustee" value={listing.trustee} />
          <Row label="Original loan" value={fmt(listing.original_principal)} />
          <Row label="Source" value={listing.source} />
          {listing.source_url && (
            <div className="py-2 text-sm">
              <a href={listing.source_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                View original notice →
              </a>
            </div>
          )}
        </div>

        {/* Notice text */}
        {listing.notice_text && (
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="font-semibold text-gray-900 mb-3">Full notice</h2>
            <p className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{listing.notice_text}</p>
          </div>
        )}
      </main>
    </div>
  )
}
