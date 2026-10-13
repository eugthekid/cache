import type { ProductFields, VariantKind } from '../api/client'
import { PRODUCT_TYPES, categoryOptions, withCurrent } from './itemOptions'

interface ItemDetailsProps {
  productType: string | null
  category: string | null
  /** Omit for a family, where each variant has its own kind. */
  variantKind?: VariantKind
  /** Categories already in use, so they're offered alongside the defaults. */
  categories: string[]
  onChange: (fields: ProductFields) => void
}

/**
 * Three dropdowns that describe an item: what kind of product it is, which
 * category it's in, and whether it's a plain product, a variant you chose, or
 * a blind pick. Saves as soon as one changes.
 */
function ItemDetails({ productType, category, variantKind, categories, onChange }: ItemDetailsProps): React.JSX.Element {
  const field = (label: string, control: React.ReactNode): React.JSX.Element => (
    <label style={{ display: 'block', minWidth: 150 }}>
      <div className="field-label">{label}</div>
      <div style={{ marginTop: 4 }}>{control}</div>
    </label>
  )
  const selectStyle = { height: 30, padding: '0 10px', fontSize: 12 }
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      {field(
        'Type',
        <select
          className="field-input"
          style={selectStyle}
          value={productType ?? ''}
          onChange={(e) => onChange({ product_type: e.target.value })}
        >
          <option value="">Not set</option>
          {withCurrent(PRODUCT_TYPES, productType).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      )}
      {field(
        'Category',
        <select
          className="field-input"
          style={selectStyle}
          value={category ?? ''}
          onChange={(e) => onChange({ category: e.target.value })}
        >
          <option value="">Uncategorized</option>
          {withCurrent(categoryOptions(categories), category).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      )}
      {variantKind !== undefined &&
        field(
          'Variant',
          <select
            className="field-input"
            style={selectStyle}
            value={variantKind ?? ''}
            onChange={(e) => onChange({ variant_kind: e.target.value as 'specific' | 'random' | '' })}
          >
            <option value="">Standard (no variants)</option>
            <option value="specific">Specific variant</option>
            <option value="random">Random variant</option>
          </select>
        )}
    </div>
  )
}

export default ItemDetails
