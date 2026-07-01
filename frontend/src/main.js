import './styles.css'
import {
    analyzeDetailPlan,
    downloadDetailPlanFile,
    getPoiSettings,
    savePoiSettings,
    searchForParcel,
} from "./api/parcels.js"
import { getRequiredElement, classifyParcelSearchInput } from "./utils/utils.js"
import {
    clearNoiseOverlay,
    clearPoiOverlay,
    createMap,
    focusParcelByAddress,
    focusParcelByTunnus,
    focusPoiOnMap,
    getAddressSuggestions,
    setNoiseOverlay,
    setPoiOverlay,
} from "./map/map.js"

const SHOW_DEBUG_HTML = import.meta.env.VITE_SHOW_DEBUG_HTML === 'true'

const searchForm = getRequiredElement('search-bar', HTMLFormElement)
const searchButton = getRequiredElement('search-button', HTMLButtonElement)
const searchInput = getRequiredElement('search-input', HTMLInputElement)
const searchSuggestions = getRequiredElement('search-suggestions', HTMLElement)
const resultsPanel = getRequiredElement('results-panel', HTMLElement)
searchInput.name = `parcel-search-${Date.now()}`

if (SHOW_DEBUG_HTML) {
    document.body.classList.add('debug-enabled')
}

const POI_COLORS = [
    '#2563eb',
    '#16a34a',
    '#dc2626',
    '#9333ea',
    '#0891b2',
    '#ca8a04',
    '#db2777',
    '#475569',
]

const DETAIL_FIELD_ORDER = [
    'krundi_pind_m2',
    'taisehitus_pct',
    'ehitusalune_pind_m2',
    'brutopind_m2',
    'korruselisus',
    'hoonete_lubatud_korgused_m',
]

const HIDDEN_BUILDING_FIELD_KEYS = new Set([
    'hoonete_arv',
    'kasutusotstarve',
    'omandivorm',
])

let currentPoiCollection = emptyFeatureCollection()
let currentPoiFeaturesByKey = new Map()
let currentNoiseGeoJson = null
let poiOverlayVisible = false
let noiseOverlayVisible = false
let closestAddressSuggestion = ''
let currentAddressSuggestions = []
let activeSuggestionIndex = -1
let lastSearchValue = ''

function emptyFeatureCollection() {
    return {
        type: 'FeatureCollection',
        features: [],
    }
}

function createElement(tagName, className, text) {
    const element = document.createElement(tagName)
    if (className) {
        element.className = className
    }
    if (text !== undefined && text !== null) {
        element.textContent = String(text)
    }
    return element
}

function appendText(parent, tagName, text, className) {
    const element = createElement(tagName, className, text)
    parent.appendChild(element)
    return element
}

function markDebug(element) {
    element.setAttribute('debug', '')
    if (!SHOW_DEBUG_HTML) {
        element.classList.add('debug-hidden')
    }
    return element
}

function isPresent(value) {
    return value !== null && value !== undefined && value !== ''
}

function asItems(group) {
    return Array.isArray(group?.items) ? group.items : []
}

function groupCount(group) {
    return group?.count ?? asItems(group).length
}

function formatNumber(value, maximumFractionDigits = 1) {
    if (typeof value !== 'number' || Number.isNaN(value)) {
        return value
    }

    return new Intl.NumberFormat('et-EE', {
        maximumFractionDigits,
    }).format(value)
}

function formatPercent(value) {
    if (typeof value !== 'number' || Number.isNaN(value)) {
        return null
    }

    return `${formatNumber(value, 1)}%`
}

function formatDistance(value) {
    if (typeof value !== 'number' || Number.isNaN(value)) {
        return null
    }

    if (value >= 1000) {
        return `${formatNumber(value / 1000, 1)} km`
    }

    return `${Math.round(value)} m`
}

function formatDate(value) {
    if (!isPresent(value)) {
        return null
    }

    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
        return String(value)
    }

    return new Intl.DateTimeFormat('et-EE', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    }).format(date)
}

function formatUnit(unit) {
    if (!unit) {
        return ''
    }

    const normalized = String(unit).trim().toLowerCase()
    if (['m2', 'm²', 'sqm'].includes(normalized)) {
        return 'm²'
    }
    if (['degree', 'degrees', 'deg', 'kraadi', '°'].includes(normalized)) {
        return '°'
    }
    return unit
}

function formatFieldValue(value, unit) {
    if (Array.isArray(value)) {
        return value.filter(isPresent).join(', ')
    }

    if (!isPresent(value)) {
        return 'Teadmata'
    }

    const formattedUnit = formatUnit(unit)
    const formattedValue = formatNumber(value)
    if (formattedUnit === '%' || formattedUnit === '°') {
        return `${formattedValue}${formattedUnit}`
    }
    if (formattedUnit) {
        return `${formattedValue} ${formattedUnit}`
    }
    return String(formattedValue)
}

function websiteHref(value) {
    if (!isPresent(value)) {
        return null
    }

    const text = String(value).trim()
    if (!text) {
        return null
    }

    return /^https?:\/\//i.test(text) ? text : `https://${text}`
}

function websiteLabel(value) {
    if (!isPresent(value)) {
        return null
    }

    const href = websiteHref(value)
    if (!href) {
        return null
    }

    try {
        return new URL(href).hostname.replace(/^www\./i, '')
    } catch {
        return String(value).trim().replace(/^https?:\/\//i, '').replace(/^www\./i, '').split('/')[0]
    }
}

function titleForItem(item) {
    return item?.nimetus || item?.nimi || item?.plannim || item?.id || item?.kovid || 'Nimetu kirje'
}

function metaFromFields(item, fields) {
    return fields
        .map((field) => {
            const value = item?.[field]
            if (!isPresent(value)) {
                return null
            }
            if (field.includes('timeposition')) {
                return formatDate(value)
            }
            if (field === 'parcel_coverage_pct') {
                return formatPercent(value)
            }
            return String(formatNumber(value))
        })
        .filter(Boolean)
        .join(' · ')
}

function appendLink(parent, item) {
    const href = item?.url || item?.planviide || item?.kpois_viide || item?.failid
    if (!href) {
        return
    }

    const link = createElement('a', 'result-link', 'Ava viide')
    link.href = href
    link.target = '_blank'
    link.rel = 'noreferrer'
    parent.appendChild(link)
}

function createSection(title, options = {}) {
    const section = createElement('section', 'dashboard-section reveal')
    const header = createElement('div', 'section-header')
    appendText(header, 'p', title, 'eyebrow')

    if (isPresent(options.count)) {
        appendText(header, 'span', String(options.count), 'count-badge')
    }

    section.appendChild(header)
    if (options.summary) {
        appendText(section, 'p', options.summary, 'section-summary')
    }

    return section
}

function appendEmpty(parent, text = 'Seoseid ei leitud.') {
    const empty = createElement('p', 'empty-state', text)
    parent.appendChild(empty)
    return empty
}

function appendBadge(parent, text, modifier, options = {}) {
    const className = modifier ? `status-badge ${modifier}` : 'status-badge'
    const badge = appendText(parent, 'span', text, className)
    if (options.debug) {
        markDebug(badge)
    }
    return badge
}

function appendDebugMeta(parent, text, className = 'result-meta') {
    if (!text) {
        return null
    }

    return markDebug(appendText(parent, 'p', text, className))
}

function renderParcelHero(parent, parcel) {
    const header = createElement('header', 'parcel-hero reveal')
    appendText(header, 'p', 'Kinnistu ülevaade', 'eyebrow')
    appendText(header, 'h1', parcel.l_aadress || parcel.tunnus || 'Valitud kinnistu')
    parent.appendChild(header)
}

function landUseRows(parcel) {
    const rows = []
    for (const index of [1, 2, 3]) {
        const use = parcel[`siht${index}`]
        const pct = parcel[`so_prts${index}`]
        if (!isPresent(use)) {
            continue
        }

        rows.push(`${use}${isPresent(pct) ? ` ${formatPercent(Number(pct)) || `${pct}%`}` : ''}`)
    }
    return rows
}

function renderParcelFacts(parent, parcel) {
    const section = createSection('KINNISTU ANDMED', {
        summary: 'Põhiandmed katastri kirjest.',
    })

    const landUses = landUseRows(parcel)
    const facts = [
        ['Aadress', parcel.l_aadress],
        ['Katastritunnus', parcel.tunnus],
        ['Pindala', parcel.pindala ? `${formatNumber(parcel.pindala, 0)} m²` : null],
        ['Omandivorm', parcel.omvorm],
        ['Sihtotstarbed', landUses.length ? landUses.join(', ') : parcel.sihtotstarve || parcel.sihtotstarve_1],
    ].filter(([, value]) => isPresent(value))

    if (!facts.length) {
        appendEmpty(section, 'Kinnistu põhiandmed puuduvad.')
    } else {
        const grid = createElement('dl', 'fact-grid')
        for (const [label, value] of facts) {
            const item = createElement('div', 'fact-item')
            appendText(item, 'dt', label)
            appendText(item, 'dd', value)
            grid.appendChild(item)
        }
        section.appendChild(grid)
    }

    parent.appendChild(section)
}

function renderListGroup(parent, items, fields, emptyText, limit = 5, options = {}) {
    if (!items.length) {
        appendEmpty(parent, emptyText)
        return
    }

    const list = createElement('ul', 'compact-list')
    for (const item of items.slice(0, limit)) {
        const listItem = createElement('li')
        appendText(listItem, 'span', titleForItem(item), 'result-title')
        const meta = metaFromFields(item, fields)
        if (meta) {
            const metaElement = appendText(listItem, 'span', meta, 'result-meta')
            if (options.debugMeta) {
                markDebug(metaElement)
            }
        }
        appendLink(listItem, item)
        list.appendChild(listItem)
    }
    parent.appendChild(list)

    if (items.length > limit) {
        const details = createElement('details', 'more-details')
        appendText(details, 'summary', `Kuva veel ${items.length - limit}`)
        const moreList = createElement('ul', 'compact-list')
        for (const item of items.slice(limit)) {
            const listItem = createElement('li')
            appendText(listItem, 'span', titleForItem(item), 'result-title')
            const meta = metaFromFields(item, fields)
            if (meta) {
                const metaElement = appendText(listItem, 'span', meta, 'result-meta')
                if (options.debugMeta) {
                    markDebug(metaElement)
                }
            }
            appendLink(listItem, item)
            moreList.appendChild(listItem)
        }
        details.appendChild(moreList)
        parent.appendChild(details)
    }
}

function renderPlanning(parent, detailPlans, searchValue) {
    const items = asItems(detailPlans)
    const section = createSection('PLANEERING JA EHITUSÕIGUS', {
        summary: items.length
            ? 'Seletuskirja põhjal saab analüüsida ehitusõigusi.'
            : 'Selle kinnistuga seotud seletuskirja ei leitud.',
    })

    renderListGroup(
        section,
        items,
        ['kovid', 'planseis_nimi', 'kehtestkp_timeposition', 'parcel_coverage_pct'],
        'Seletuskirju ei leitud.',
        3,
        { debugMeta: true },
    )

    if (items.length) {
        appendDetailPlanDownloads(section, searchValue)
        appendDetailPlanAnalysis(section, searchValue)
    }

    parent.appendChild(section)
}

function appendDetailPlanDownloads(parent, searchValue) {
    const panel = createElement('div', 'download-actions')
    const skButton = createElement('button', 'secondary-button', 'Laadi seletuskiri')
    skButton.type = 'button'
    panel.appendChild(skButton)

    const planButton = createElement('button', 'secondary-button', 'Laadi detailplaneering')
    planButton.type = 'button'
    panel.appendChild(planButton)

    const message = createElement('div', 'download-message')
    parent.appendChild(panel)
    parent.appendChild(message)

    skButton.addEventListener('click', () => handleDetailPlanDownload(searchValue, 'seletuskiri', skButton, message))
    planButton.addEventListener('click', () => handleDetailPlanDownload(searchValue, 'detailplaneering', planButton, message))
}

function appendDetailPlanAnalysis(parent, searchValue) {
    const panel = createElement('div', 'analysis-panel')
    const actions = createElement('div', 'analysis-actions')
    const button = createElement('button', 'primary-button analysis-button', 'Analüüsi ehitusõigust')
    button.type = 'button'
    actions.appendChild(button)
    panel.appendChild(actions)

    const status = createElement('div', 'analysis-status')
    panel.appendChild(status)

    const output = createElement('div', 'analysis-output')
    appendEmpty(output, 'Analüüsi tulemus ilmub siia pärast käivitamist.')
    panel.appendChild(output)
    parent.appendChild(panel)

    button.addEventListener('click', async () => {
        button.disabled = true
        button.textContent = 'Analüüs käib'
        renderAnalysisLoading(status, 'Loen PDFi')

        try {
            const regexResult = await analyzeDetailPlan(searchValue, {
                enableLlmResolver: false,
            })
            renderAnalysisResult(output, regexResult, {
                title: 'Reeglipõhine tulemus',
            })
            renderAnalysisLoading(status, 'AI täpsustab')

            try {
                const aiResult = await analyzeDetailPlan(searchValue, {
                    enableLlmResolver: true,
                })
                renderAnalysisResult(output, aiResult, {
                    title: 'AI-ga täiendatud tulemus',
                })
                status.replaceChildren()
            } catch (error) {
                status.replaceChildren()
                appendAnalysisMessage(output, `AI täiendamine ebaõnnestus: ${error.message}`, 'warning')
            }
        } catch (error) {
            status.replaceChildren()
            output.replaceChildren()
            appendAnalysisMessage(output, error.message, 'error')
        } finally {
            button.disabled = false
            button.textContent = 'Analüüsi uuesti'
        }
    })
}

async function handleDetailPlanDownload(searchValue, fileType, button, output) {
    const originalText = button.textContent
    button.disabled = true
    button.textContent = 'Laen'
    output.replaceChildren()

    try {
        const { blob, filename } = await downloadDetailPlanFile(searchValue, fileType)
        const href = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = href
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(href)
    } catch (error) {
        appendAnalysisMessage(output, error.message, 'warning')
    } finally {
        button.disabled = false
        button.textContent = originalText
    }
}

function renderAnalysisLoading(parent, text) {
    parent.replaceChildren()
    const loader = createElement('div', 'ai-loader')
    appendText(loader, 'span', '', 'loader-orb')
    appendText(loader, 'strong', text)
    parent.appendChild(loader)
}

function appendAnalysisMessage(parent, text, type = 'info') {
    const message = createElement('p', `analysis-message ${type}`, text)
    parent.appendChild(message)
}

function renderAnalysisResult(parent, result, options) {
    parent.replaceChildren()

    const header = createElement('div', 'analysis-result-header')
    appendText(header, 'h3', options.title)
    const status = result?.status ? `Staatus: ${result.status}` : 'Staatus teadmata'
    appendBadge(header, status, result?.status === 'ok' ? 'success' : 'warning', { debug: true })
    parent.appendChild(header)

    if (Array.isArray(result?.setup_issues) && result.setup_issues.length) {
        const issues = createElement('div', 'review-box')
        appendText(issues, 'strong', 'Seadistuse märkused')
        for (const issue of result.setup_issues) {
            appendText(issues, 'p', issue)
        }
        parent.appendChild(issues)
    }

    renderBuildingRightFields(parent, result?.building_right)

    if (Array.isArray(result?.sources) && result.sources.length) {
        const details = markDebug(createElement('details', 'evidence-details'))
        appendText(details, 'summary', `Allikad (${result.sources.length})`)
        for (const source of result.sources) {
            const row = createElement('p')
            row.textContent = `${source.pdf || 'PDF'}${source.page ? `, lk ${source.page}` : ''}: ${source.reason || 'allikas'}`
            details.appendChild(row)
        }
        parent.appendChild(details)
    }
}

function firstEvidencePage(field) {
    if (field?.evidence?.page) {
        return field.evidence.page
    }

    for (const candidate of field?.candidates || []) {
        if (candidate.evidence?.page) {
            return candidate.evidence.page
        }
    }

    return null
}

function renderBuildingRightFields(parent, buildingRight) {
    const fields = buildingRight?.fields || {}
    const fieldEntries = Object.entries(fields)
        .filter(([key]) => !HIDDEN_BUILDING_FIELD_KEYS.has(key))

    if (!fieldEntries.length) {
        appendEmpty(parent, 'Ehitusõiguse välju ei leitud.')
        return
    }

    const orderedEntries = fieldEntries.sort(([keyA], [keyB]) => {
        const indexA = DETAIL_FIELD_ORDER.indexOf(keyA)
        const indexB = DETAIL_FIELD_ORDER.indexOf(keyB)
        return (indexA === -1 ? 999 : indexA) - (indexB === -1 ? 999 : indexB)
    })

    const grid = createElement('div', 'building-fields')
    for (const [, field] of orderedEntries) {
        const card = createElement('article', 'field-card')
        const titleRow = createElement('div', 'field-title-row')
        appendText(titleRow, 'h4', field.label || field.key || 'Väli')
        if (field.needs_review?.length) {
            appendBadge(titleRow, 'Vajab kontrolli', 'warning')
        }
        card.appendChild(titleRow)

        appendText(card, 'p', formatFieldValue(field.value, field.unit), 'field-value')

        const page = firstEvidencePage(field)
        if (page) {
            appendText(card, 'p', `lk ${page}`, 'field-page')
        }

        const meta = [
            field.source_type ? `Allikas: ${field.source_type}` : null,
            typeof field.confidence === 'number' ? `Kindlus: ${formatPercent(field.confidence * 100)}` : null,
        ].filter(Boolean).join(' · ')
        appendDebugMeta(card, meta)

        if (field.needs_review?.length) {
            const review = createElement('div', 'review-box')
            for (const item of field.needs_review) {
                appendText(review, 'p', item.message || 'Vajab kontrolli')
            }
            card.appendChild(review)
        }

        appendEvidence(card, field)
        grid.appendChild(card)
    }

    parent.appendChild(grid)
}

function appendEvidence(parent, field) {
    const evidenceItems = []
    if (field.evidence) {
        evidenceItems.push(field.evidence)
    }
    for (const candidate of field.candidates || []) {
        if (candidate.evidence) {
            evidenceItems.push(candidate.evidence)
        }
    }

    if (!evidenceItems.length) {
        return
    }

    const details = markDebug(createElement('details', 'evidence-details'))
    appendText(details, 'summary', `Tõendus (${evidenceItems.length})`)

    for (const evidence of evidenceItems.slice(0, 4)) {
        const item = createElement('blockquote')
        if (evidence.pdf) {
            appendText(item, 'cite', evidence.pdf)
        }
        appendText(item, 'p', evidence.text || 'Tõenduse tekst puudub.')
        details.appendChild(item)
    }

    parent.appendChild(details)
}

function renderRisks(parent, response) {
    const heritage = asItems(response.heritage_pois)
    const restrictions = asItems(response.restriction_areas)
    const total = heritage.length + restrictions.length
    const section = createSection('PIIRANGUD', {
        count: total,
        summary: total
            ? 'Kinnistuga kattuvad või seotud kaitse- ja kitsendusalad.'
            : 'Olulisi piiranguid selle vastuse põhjal ei leitud.',
    })

    const grid = createElement('div', 'split-grid')

    const heritageCard = createElement('div', 'sub-card')
    appendText(heritageCard, 'h3', `Muinsuskaitse (${groupCount(response.heritage_pois)})`)
    renderListGroup(
        heritageCard,
        heritage,
        ['klass', 'kpo_liik_kood_vaartus', 'nahtus_id_vaartus'],
        'Muinsuskaitse objekte ei leitud.',
        4,
    )
    grid.appendChild(heritageCard)

    const restrictionCard = createElement('div', 'sub-card')
    appendText(restrictionCard, 'h3', `Kitsendusalad (${groupCount(response.restriction_areas)})`)
    renderListGroup(
        restrictionCard,
        restrictions,
        ['klass', 'voond_liik_id_vaartus', 'parcel_coverage_pct'],
        'Kitsendusalasid ei leitud.',
        4,
    )
    grid.appendChild(restrictionCard)

    section.appendChild(grid)
    parent.appendChild(section)
}

function extractNoiseGeoJson(noiseLevels) {
    const candidate = noiseLevels?.geojson
        || noiseLevels?.noise_geojson
        || noiseLevels?.areas_geojson
        || noiseLevels?.areas
    if (!candidate) {
        return null
    }

    if (candidate.type === 'FeatureCollection') {
        return candidate
    }

    if (Array.isArray(candidate.features)) {
        return {
            type: 'FeatureCollection',
            features: candidate.features,
        }
    }

    return null
}

function renderEnvironment(parent, noiseLevels) {
    const section = createSection('MÜRA', {
        summary: 'Mürataseme hinnang kinnistul ja lähialas.',
    })

    if (!noiseLevels || typeof noiseLevels !== 'object') {
        appendEmpty(section, 'Müraandmeid ei ole saadaval.')
        parent.appendChild(section)
        return
    }

    const cards = createElement('div', 'noise-grid')
    appendNoiseCard(cards, 'Kinnistul', noiseLevels.unbuffered)
    appendNoiseCard(cards, `Lähiala ${noiseLevels.buffer_m ?? 50} m`, noiseLevels.buffered)
    section.appendChild(cards)
    parent.appendChild(section)
}

function appendNoiseCard(parent, title, noise) {
    const card = createElement('article', 'noise-card')
    appendText(card, 'h3', title)

    if (!noise || typeof noise !== 'object') {
        appendEmpty(card, 'Müraandmed puuduvad.')
        parent.appendChild(card)
        return
    }

    const dbValue = noise.avg_db ?? noise.avg_db_upper
    const display = noise.label || (dbValue ? `${formatNumber(dbValue, 1)} dB` : 'Teadmata')
    appendText(card, 'p', display, 'noise-value')

    const meter = createElement('div', 'noise-meter')
    const indicator = createElement('span', 'noise-indicator')
    const percent = Math.max(0, Math.min(100, (((dbValue ?? 40) - 40) / 40) * 100))
    indicator.style.left = `${percent}%`
    meter.appendChild(indicator)
    card.appendChild(meter)

    const meta = [
        noise.result_type === 'upper_bound' ? 'Ülempiiri hinnang' : 'Keskmine hinnang',
        typeof noise.mapped_pct === 'number' ? `Kaetus ${formatPercent(noise.mapped_pct)}` : null,
    ].filter(Boolean).join(' · ')
    appendDebugMeta(card, meta)
    parent.appendChild(card)
}

function stableColorForLabel(label) {
    const text = label || 'Muu'
    let hash = 0
    for (let index = 0; index < text.length; index += 1) {
        hash = (hash * 31 + text.charCodeAt(index)) % POI_COLORS.length
    }
    return POI_COLORS[hash]
}

function poiKey(categoryId, index) {
    return `${categoryId}:${index}`
}

function poiFeatureFromItem(categoryId, group, item, index) {
    if (item?.geometry?.type !== 'Point' || !Array.isArray(item.geometry.coordinates)) {
        return null
    }

    const categoryLabel = group?.label || categoryId
    const subgroup = item.alamgrupp || item.grupp || item.poi_type || ''
    const distanceLabel = formatDistance(item.kaugus_m) || ''
    const website = item.www || ''

    return {
        type: 'Feature',
        geometry: item.geometry,
        properties: {
            poiKey: poiKey(categoryId, index),
            name: item.nimi || categoryLabel,
            address: item.aadress || '',
            categoryId,
            categoryLabel,
            subgroup,
            distanceLabel,
            website,
            color: stableColorForLabel(categoryLabel),
        },
    }
}

function buildPoiFeatureCollection(nearbyPois) {
    const features = []
    const featureMap = new Map()
    for (const [categoryId, group] of Object.entries(nearbyPois || {})) {
        asItems(group).forEach((item, index) => {
            const feature = poiFeatureFromItem(categoryId, group, item, index)
            if (!feature) {
                return
            }

            features.push(feature)
            featureMap.set(feature.properties.poiKey, feature)
        })
    }

    currentPoiFeaturesByKey = featureMap
    return {
        type: 'FeatureCollection',
        features,
    }
}

function focusPoiFromPanel(feature, toggle) {
    if (!feature) {
        return
    }

    if (!poiOverlayVisible) {
        poiOverlayVisible = true
        setPoiOverlay(map, currentPoiCollection)
        toggle.textContent = 'Peida kaardilt'
    }

    focusPoiOnMap(map, feature)
}

function appendWebsiteLink(parent, www) {
    const href = websiteHref(www)
    if (!href) {
        return
    }

    const link = createElement('a', 'poi-website-link', websiteLabel(www))
    link.href = href
    link.target = '_blank'
    link.rel = 'noreferrer'
    parent.appendChild(link)
}

function addPoiSettingsRow(parent, query = {}) {
    const row = createElement('div', 'poi-settings-row')
    row.dataset.queryLabel = query.label || ''
    appendText(row, 'span', query.label || 'Huvipunkt', 'poi-settings-label')

    const limitInput = createElement('input')
    limitInput.type = 'number'
    limitInput.value = String(query.limit ?? 3)
    limitInput.name = 'query-limit'
    limitInput.inputMode = 'numeric'
    limitInput.min = '0'
    limitInput.max = '5'
    limitInput.step = '1'
    limitInput.addEventListener('input', () => {
        syncPoiSettingsRow(row)
        syncPoiSettingsCategory(row.closest('.poi-settings-category'))
    })
    row.appendChild(limitInput)

    syncPoiSettingsRow(row)
    parent.appendChild(row)
}

function poiCategoryIsDisabled(category) {
    const queries = category?.queries || []
    return Boolean(category?.['user-disabled']) || poiCategoryAllLimitsZero(category)
}

function poiCategoryAllLimitsZero(category) {
    const queries = category?.queries || []
    return queries.length > 0 && queries.every((query) => Number(query.limit || 0) === 0)
}

function poiCategoryHasExplicitDisabled(category) {
    return Boolean(category?.['user-disabled']) && !poiCategoryAllLimitsZero(category)
}

function syncPoiSettingsRow(row) {
    const value = Number(row.querySelector('[name="query-limit"]')?.value || 0)
    row.classList.toggle('is-zero', value === 0)
}

function syncPoiSettingsCategory(categoryElement) {
    if (!categoryElement) {
        return
    }

    const inputs = [...categoryElement.querySelectorAll('[name="query-limit"]')]
    const allZero = inputs.length > 0 && inputs.every((input) => Number(input.value || 0) === 0)
    const userDisabled = categoryElement.dataset.userDisabled === 'true'
    const disabled = userDisabled || allZero
    categoryElement.classList.toggle('is-disabled', disabled)
    categoryElement.querySelector('.poi-settings-disable')?.setAttribute('aria-pressed', String(disabled))
}

function setPoiSettingsCategoryDisabled(categoryElement, disabled) {
    categoryElement.dataset.userDisabled = String(disabled)
    syncPoiSettingsCategory(categoryElement)
}

function setPoiSettingsMessage(parent, text, type = 'warning') {
    parent.querySelector('.poi-settings-message')?.remove()
    if (!text) {
        return
    }

    const message = createElement('p', `poi-settings-message ${type}`, text)
    parent.appendChild(message)
}

function validatePoiSettingsForm(form, maxQueryLimit) {
    for (const input of form.querySelectorAll('[name="query-limit"]')) {
        const rawValue = input.value.trim()
        const value = Number(rawValue)
        if (!rawValue || !Number.isInteger(value) || value < 0 || value > maxQueryLimit) {
            input.classList.add('is-invalid')
            input.focus()
            return false
        }
        input.classList.remove('is-invalid')
    }
    return true
}

function buildPoiSettingsFromForm(form, baseCategories) {
    const categories = structuredClone(baseCategories)
    for (const categoryElement of form.querySelectorAll('.poi-settings-category')) {
        const categoryId = categoryElement.dataset.categoryId
        const category = categories[categoryId]
        if (!category) {
            continue
        }

        category.queries = (category.queries || []).map((query, index) => ({
            ...query,
            limit: Number(categoryElement.querySelector(`[name="query-limit"][data-query-index="${index}"]`)?.value ?? query.limit ?? 3),
        }))
        categories[categoryId]['user-disabled'] = categoryElement.dataset.userDisabled === 'true'
            || category.queries.every((query) => Number(query.limit || 0) === 0)
    }
    return categories
}

function renderPoiSettingsRows(rows, category) {
    rows.replaceChildren()
    ;(category.queries || []).forEach((query, index) => {
        addPoiSettingsRow(rows, query)
        rows.lastElementChild.querySelector('[name="query-limit"]').dataset.queryIndex = String(index)
    })
}

function setPoiSettingsFormValues(form, categories) {
    for (const categoryElement of form.querySelectorAll('.poi-settings-category')) {
        const category = categories[categoryElement.dataset.categoryId]
        if (!category) {
            continue
        }

        ;(category.queries || []).forEach((query, index) => {
            const input = categoryElement.querySelector(`[name="query-limit"][data-query-index="${index}"]`)
            if (input) {
                input.value = String(query.limit ?? 3)
                input.classList.remove('is-invalid')
                syncPoiSettingsRow(input.closest('.poi-settings-row'))
            }
        })
        setPoiSettingsCategoryDisabled(categoryElement, poiCategoryHasExplicitDisabled(category))
    }
}

function closePoiSettingsModal() {
    document.querySelector('.poi-settings-backdrop')?.remove()
}

function setPoiSettingsCategoriesOpen(form, open) {
    form.querySelectorAll('.poi-settings-category').forEach((categoryElement) => {
        categoryElement.open = open
    })
}

async function openPoiSettingsModal() {
    const backdrop = createElement('div', 'poi-settings-backdrop')
    const modal = createElement('div', 'poi-settings-modal')
    backdrop.appendChild(modal)
    document.body.appendChild(backdrop)

    appendText(modal, 'h2', 'POI seaded')
    appendEmpty(modal, 'Laen seadeid.')

    try {
        const settings = await getPoiSettings()
        const defaultCategories = settings.default_poi_categories || settings.poi_categories || {}
        const maxQueryLimit = settings.max_query_limit || 5
        modal.replaceChildren()

        const header = createElement('div', 'poi-settings-header')
        appendText(header, 'h2', 'POI seaded')
        const headerActions = createElement('div', 'poi-settings-header-actions')
        const openAllButton = createElement('button', 'secondary-button', 'Ava kõik')
        openAllButton.type = 'button'
        headerActions.appendChild(openAllButton)
        const closeAllButton = createElement('button', 'secondary-button', 'Sulge kõik')
        closeAllButton.type = 'button'
        headerActions.appendChild(closeAllButton)
        const closeButton = createElement('button', 'secondary-button', 'Sulge')
        closeButton.type = 'button'
        closeButton.addEventListener('click', closePoiSettingsModal)
        headerActions.appendChild(closeButton)
        header.appendChild(headerActions)
        modal.appendChild(header)

        const form = createElement('form', 'poi-settings-form')
        form.noValidate = true
        openAllButton.addEventListener('click', () => setPoiSettingsCategoriesOpen(form, true))
        closeAllButton.addEventListener('click', () => setPoiSettingsCategoriesOpen(form, false))
        const categoriesGrid = createElement('div', 'poi-settings-grid')
        for (const [categoryId, category] of Object.entries(settings.poi_categories || {})) {
            const section = createElement('details', 'poi-settings-category')
            section.dataset.categoryId = categoryId
            section.open = true

            const summary = createElement('summary', 'poi-settings-category-header')
            const swatch = createElement('button', 'poi-swatch poi-settings-disable')
            swatch.type = 'button'
            swatch.style.backgroundColor = stableColorForLabel(category.label)
            swatch.addEventListener('click', (event) => {
                event.preventDefault()
                event.stopPropagation()
                setPoiSettingsCategoryDisabled(section, section.dataset.userDisabled !== 'true')
            })
            summary.appendChild(swatch)
            appendText(summary, 'span', category.label || categoryId)
            section.appendChild(summary)

            const rows = createElement('div', 'poi-settings-rows')
            renderPoiSettingsRows(rows, category)
            section.appendChild(rows)
            setPoiSettingsCategoryDisabled(section, poiCategoryHasExplicitDisabled(category))
            categoriesGrid.appendChild(section)
        }
        form.appendChild(categoriesGrid)

        const footer = createElement('div', 'poi-settings-footer')
        const resetButton = createElement('button', 'secondary-button', 'Lähtesta')
        resetButton.type = 'button'
        resetButton.addEventListener('click', () => {
            setPoiSettingsFormValues(form, defaultCategories)
            setPoiSettingsMessage(modal, '')
        })
        footer.appendChild(resetButton)

        const saveButton = createElement('button', 'primary-button', 'Salvesta')
        saveButton.type = 'submit'
        footer.appendChild(saveButton)
        form.appendChild(footer)
        modal.appendChild(form)

        form.addEventListener('submit', async (event) => {
            event.preventDefault()
            setPoiSettingsMessage(modal, '')
            if (!validatePoiSettingsForm(form, maxQueryLimit)) {
                setPoiSettingsMessage(modal, `Sisesta igale reale täisarv vahemikus 0-${maxQueryLimit}.`)
                return
            }

            saveButton.disabled = true
            saveButton.textContent = 'Salvestan'
            try {
                await savePoiSettings(buildPoiSettingsFromForm(form, defaultCategories))
                closePoiSettingsModal()
                if (lastSearchValue || searchInput.value) {
                    await handleParcelSearch(lastSearchValue || searchInput.value)
                }
            } catch (error) {
                setPoiSettingsMessage(modal, error.message || 'Seadete salvestamine ebaõnnestus.', 'error')
            } finally {
                saveButton.disabled = false
                saveButton.textContent = 'Salvesta'
            }
        })

        backdrop.addEventListener('click', (event) => {
            if (event.target === backdrop) {
                closePoiSettingsModal()
            }
        })
    } catch (error) {
        modal.replaceChildren()
        appendText(modal, 'h2', 'POI seaded')
        appendAnalysisMessage(modal, error.message, 'error')
        const closeButton = createElement('button', 'secondary-button', 'Sulge')
        closeButton.type = 'button'
        closeButton.addEventListener('click', closePoiSettingsModal)
        modal.appendChild(closeButton)
    }
}

function renderPoiItem(parent, categoryId, group, item, index, toggle) {
    const feature = currentPoiFeaturesByKey.get(poiKey(categoryId, index))
    const listItem = createElement('li', 'poi-list-item')

    const button = createElement('button', 'poi-item-button')
    button.type = 'button'
    button.addEventListener('click', () => focusPoiFromPanel(feature, toggle))

    const top = createElement('span', 'poi-item-top')
    appendText(top, 'span', item.nimi || 'Nimetu objekt', 'result-title')
    const distance = formatDistance(item.kaugus_m)
    if (distance) {
        appendText(top, 'span', distance, 'poi-distance')
    }
    button.appendChild(top)

    const meta = createElement('span', 'poi-item-meta')
    appendText(meta, 'span', item.alamgrupp || item.grupp || 'Muu')
    if (item.aadress) {
        appendText(meta, 'span', item.aadress)
    }
    button.appendChild(meta)

    listItem.appendChild(button)
    appendWebsiteLink(listItem, item.www)
    parent.appendChild(listItem)
}

function renderNearby(parent, nearbyPois) {
    const groups = Object.entries(nearbyPois || {})
        .map(([key, group]) => [key, group, asItems(group)])
        .filter(([, , items]) => items.length)
    const itemCount = groups.reduce((sum, [, , items]) => sum + items.length, 0)

    const section = createSection('TEENUSED LÄHEDUSES', {
        count: itemCount,
        summary: itemCount
            ? 'Lähimad teenused ja huvipunktid kategooriate kaupa.'
            : 'Läheduses olevaid huvipunkte ei leitud.',
    })

    const toolbar = createElement('div', 'section-toolbar')
    const toggle = createElement('button', 'secondary-button', poiOverlayVisible ? 'Peida kaardilt' : 'Näita kaardil')
    toggle.type = 'button'
    toggle.disabled = !currentPoiCollection.features.length
    toolbar.appendChild(toggle)
    const settingsButton = createElement('button', 'secondary-button', 'Seadista')
    settingsButton.type = 'button'
    settingsButton.addEventListener('click', openPoiSettingsModal)
    toolbar.appendChild(settingsButton)
    const openAllButton = createElement('button', 'secondary-button', 'Ava kõik')
    openAllButton.type = 'button'
    toolbar.appendChild(openAllButton)
    const closeAllButton = createElement('button', 'secondary-button', 'Sulge kõik')
    closeAllButton.type = 'button'
    toolbar.appendChild(closeAllButton)
    section.appendChild(toolbar)

    toggle.addEventListener('click', () => {
        poiOverlayVisible = !poiOverlayVisible
        if (poiOverlayVisible) {
            setPoiOverlay(map, currentPoiCollection)
            toggle.textContent = 'Peida kaardilt'
        } else {
            clearPoiOverlay(map)
            toggle.textContent = 'Näita kaardil'
        }
    })

    if (!groups.length) {
        appendEmpty(section, 'Läheduses olevaid huvipunkte ei leitud.')
        parent.appendChild(section)
        return
    }

    const groupList = createElement('div', 'poi-groups')
    for (const [categoryId, group, items] of groups) {
        const category = createElement('details', 'poi-group')
        category.open = true
        const header = createElement('summary', 'poi-group-header')
        const swatch = createElement('span', 'poi-swatch')
        swatch.style.backgroundColor = stableColorForLabel(group.label)
        header.appendChild(swatch)
        appendText(header, 'h3', `${group.label || 'Huvipunktid'} (${items.length})`)
        category.appendChild(header)

        const list = createElement('ul', 'poi-list')
        items.slice(0, 3).forEach((item, index) => {
            renderPoiItem(list, categoryId, group, item, index, toggle)
        })
        category.appendChild(list)

        if (items.length > 3) {
            const details = createElement('details', 'more-details')
            appendText(details, 'summary', `Kuva veel ${items.length - 3}`)
            const moreList = createElement('ul', 'poi-list')
            items.slice(3).forEach((item, offset) => {
                renderPoiItem(moreList, categoryId, group, item, offset + 3, toggle)
            })
            details.appendChild(moreList)
            category.appendChild(details)
        }

        groupList.appendChild(category)
    }

    section.appendChild(groupList)
    openAllButton.addEventListener('click', () => {
        groupList.querySelectorAll('.poi-group').forEach((groupElement) => {
            groupElement.open = true
        })
    })
    closeAllButton.addEventListener('click', () => {
        groupList.querySelectorAll('.poi-group').forEach((groupElement) => {
            groupElement.open = false
        })
    })
    parent.appendChild(section)
}

function resetPoiOverlay() {
    poiOverlayVisible = false
    currentPoiCollection = emptyFeatureCollection()
    currentPoiFeaturesByKey = new Map()
    clearPoiOverlay(map)
}

function resetNoiseOverlay() {
    noiseOverlayVisible = false
    currentNoiseGeoJson = null
    clearNoiseOverlay(map)
}

function renderParcelResponse(response, searchValue) {
    resultsPanel.replaceChildren()
    resetPoiOverlay()
    resetNoiseOverlay()

    if (response?.error) {
        const panel = createElement('div', 'empty-panel')
        appendText(panel, 'p', 'Otsing', 'eyebrow')
        appendText(panel, 'h1', 'Kinnistut ei leitud')
        appendText(panel, 'p', response.error, 'muted')
        resultsPanel.appendChild(panel)
        return
    }

    const parcel = response?.Aadress || {}
    if (parcel.l_aadress) {
        searchInput.value = parcel.l_aadress
    }
    if (parcel.tunnus) {
        focusParcelByTunnus(map, parcel.tunnus, parcel.l_aadress || searchValue)
    }
    currentPoiCollection = buildPoiFeatureCollection(response?.nearby_pois)

    const dashboard = createElement('div', 'parcel-dashboard')
    renderParcelHero(dashboard, parcel)
    renderParcelFacts(dashboard, parcel)
    renderPlanning(dashboard, response?.detail_plans, parcel.l_aadress || searchValue)
    renderRisks(dashboard, response || {})
    renderEnvironment(dashboard, response?.noise_levels)
    renderNearby(dashboard, response?.nearby_pois)
    resultsPanel.appendChild(dashboard)
}

async function handleParcelSearch(value) {
    const trimmedValue = value.trim()
    if (!trimmedValue) {
        return
    }
    lastSearchValue = trimmedValue

    searchButton.disabled = true
    searchButton.textContent = 'Otsin'
    hideAddressSuggestions()
    if (classifyParcelSearchInput(trimmedValue).type === 'address') {
        focusParcelByAddress(map, trimmedValue)
    }
    resetPoiOverlay()
    resetNoiseOverlay()
    resultsPanel.replaceChildren()
    const loading = createElement('div', 'empty-panel')
    appendText(loading, 'p', 'Otsing', 'eyebrow')
    appendText(loading, 'h1', 'Laen kinnistu andmeid')
    appendText(loading, 'p', 'Kaart jääb kasutatavaks, tulemused ilmuvad siia.', 'muted')
    resultsPanel.appendChild(loading)

    try {
        const response = await searchForParcel(trimmedValue)
        renderParcelResponse(response, trimmedValue)
    } catch (error) {
        resetPoiOverlay()
        resetNoiseOverlay()
        resultsPanel.replaceChildren()
        const panel = createElement('div', 'empty-panel')
        appendText(panel, 'p', 'Viga', 'eyebrow')
        appendText(panel, 'h1', 'Päring ebaõnnestus')
        appendText(panel, 'p', error.message, 'muted')
        resultsPanel.appendChild(panel)
    } finally {
        searchButton.disabled = false
        searchButton.textContent = 'Otsi'
    }
}

function updateAddressSuggestions() {
    const query = searchInput.value.trim()
    searchSuggestions.replaceChildren()
    currentAddressSuggestions = []
    activeSuggestionIndex = -1
    closestAddressSuggestion = ''
    searchSuggestions.hidden = true

    if (query.length < 2 || classifyParcelSearchInput(query).type !== 'address') {
        return
    }

    const suggestions = getAddressSuggestions(map, query, 20)
    currentAddressSuggestions = suggestions

    if (suggestions.length || document.activeElement === searchInput) {
        searchSuggestions.hidden = false
    }

    for (const suggestion of suggestions) {
        const option = createElement('button', 'search-suggestion-option', suggestion)
        option.type = 'button'
        option.setAttribute('role', 'option')
        option.addEventListener('mousedown', (event) => {
            event.preventDefault()
            chooseAddressSuggestion(suggestion)
        })
        searchSuggestions.appendChild(option)
    }

}

function hideAddressSuggestions() {
    searchSuggestions.hidden = true
    activeSuggestionIndex = -1
    for (const option of searchSuggestions.children) {
        option.classList.remove('is-active')
    }
}

function chooseAddressSuggestion(suggestion) {
    searchInput.value = suggestion
    hideAddressSuggestions()
    focusParcelByAddress(map, suggestion)
    searchInput.focus()
}

function setActiveSuggestion(index) {
    if (!currentAddressSuggestions.length) {
        return
    }

    activeSuggestionIndex = (index + currentAddressSuggestions.length) % currentAddressSuggestions.length
    Array.from(searchSuggestions.children).forEach((option, optionIndex) => {
        option.classList.toggle('is-active', optionIndex === activeSuggestionIndex)
    })
}

const map = createMap("map", {
    onParcelClick: async function (feature) {
        const address = feature.properties?.l_aadress
        const tunnus = feature.properties?.tunnus
        const lookupValue = tunnus || address
        if (lookupValue) {
            searchInput.value = address || lookupValue
            await handleParcelSearch(lookupValue)
        }
    },
})

searchForm.addEventListener('submit', async (event) => {
    event.preventDefault()
    await handleParcelSearch(searchInput.value)
})

searchInput.addEventListener('input', updateAddressSuggestions)
searchInput.addEventListener('focus', updateAddressSuggestions)
searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' && currentAddressSuggestions.length) {
        event.preventDefault()
        setActiveSuggestion(activeSuggestionIndex + 1)
        return
    }

    if (event.key === 'ArrowUp' && currentAddressSuggestions.length) {
        event.preventDefault()
        setActiveSuggestion(activeSuggestionIndex - 1)
        return
    }

    if (event.key === 'Enter' && activeSuggestionIndex >= 0) {
        event.preventDefault()
        chooseAddressSuggestion(currentAddressSuggestions[activeSuggestionIndex])
        return
    }

    if (event.key === 'Escape') {
        hideAddressSuggestions()
        return
    }

    if ((event.key === 'Tab' || event.key === 'ArrowRight') && closestAddressSuggestion) {
        event.preventDefault()
        chooseAddressSuggestion(closestAddressSuggestion)
    }
})


document.addEventListener('mousedown', (event) => {
    if (!searchForm.contains(event.target)) {
        hideAddressSuggestions()
    }
})
