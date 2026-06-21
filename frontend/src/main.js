import './styles.css'
import { searchForParcel } from "./api/parcels.js"
import { getRequiredElement } from "./utils/utils.js"
import { createMap } from "./map/map.js"

const searchButton = getRequiredElement('search-button', HTMLButtonElement)
const searchInput = getRequiredElement('search-input', HTMLInputElement)
const resultsPanel = getRequiredElement('results-panel', HTMLElement)

function appendText(parent, tagName, text, className) {
    const element = document.createElement(tagName)
    if (className) {
        element.className = className
    }
    element.textContent = text
    parent.appendChild(element)
    return element
}

function itemTitle(item) {
    return item.nimetus || item.nimi || item.plannim || item.id || item.kovid || 'Nimetu kirje'
}

function itemMeta(item, fields) {
    return fields
        .map((field) => item[field])
        .filter((value) => value !== null && value !== undefined && value !== '')
        .join(' · ')
}

function appendItemLink(parent, item) {
    const href = item.url || item.planviide || item.kpois_viide || item.failid
    if (!href) {
        return
    }

    const link = document.createElement('a')
    link.className = 'result-link'
    link.href = href
    link.target = '_blank'
    link.rel = 'noreferrer'
    link.textContent = 'Ava viide'
    parent.appendChild(link)
}

function appendResultSection(parent, title, group, metaFields) {
    const section = document.createElement('section')
    section.className = 'results-section'
    parent.appendChild(section)

    appendText(section, 'h3', `${title} (${group?.count ?? 0})`)

    if (!group?.items?.length) {
        appendText(section, 'p', 'Seoseid ei leitud.', 'results-empty')
        return
    }

    const list = document.createElement('ul')
    list.className = 'results-list'
    section.appendChild(list)

    for (const item of group.items.slice(0, 10)) {
        const listItem = document.createElement('li')
        list.appendChild(listItem)

        appendText(listItem, 'span', itemTitle(item), 'result-title')

        const meta = itemMeta(item, metaFields)
        if (meta) {
            appendText(listItem, 'span', meta, 'result-meta')
        }

        appendItemLink(listItem, item)
    }
}

function renderParcelResponse(response) {
    resultsPanel.replaceChildren()

    if (response.error) {
        appendText(resultsPanel, 'p', response.error, 'results-empty')
        return
    }

    const parcel = response.Aadress || {}
    appendText(
        resultsPanel,
        'h2',
        parcel.l_aadress || parcel.tunnus || 'Valitud kinnistu'
    )

    if (parcel.tunnus) {
        appendText(resultsPanel, 'p', parcel.tunnus, 'result-meta')
    }

    appendResultSection(
        resultsPanel,
        'Muinsuskaitse objektid',
        response.heritage_pois,
        ['klass', 'kpo_liik_kood_vaartus', 'nahtus_id_vaartus']
    )
    appendResultSection(
        resultsPanel,
        'Kitsendusalad',
        response.restriction_areas,
        ['klass', 'voond_liik_id_vaartus', 'parcel_coverage_pct']
    )
    appendResultSection(
        resultsPanel,
        'Detailplaneeringud',
        response.detail_plans,
        ['kovid', 'planseis_nimi', 'kehtestkp_timeposition']
    )
}

async function handleParcelSearch(value) {
    searchButton.disabled = true
    try {
        const response = await searchForParcel(value)
        renderParcelResponse(response)
    } catch (error) {
        resultsPanel.replaceChildren()
        appendText(resultsPanel, 'p', error.message, 'results-empty')
    } finally {
        searchButton.disabled = false
    }
}

const map = createMap("map", {
    onParcelClick: async function(feature) {
        await handleParcelSearch(feature.properties.tunnus)
    }
})


searchButton.addEventListener('click', async () => {
    await handleParcelSearch(searchInput.value)
})
