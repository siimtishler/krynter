import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './styles.css'

import { API_BASE_URL } from '../api/client.js'

const SHOW_DEBUG_HTML = import.meta.env.VITE_SHOW_DEBUG_HTML === 'true'
const KERESE_CENTER = [24.709819, 59.3795179]
const NOISE_AREA_SOURCE_ID = 'noise-area'
const NOISE_AREA_SOURCE_FILL_ID = 'noise-area-fill'
const NOISE_AREA_SOURCE_LINE_ID = 'noise-area-line'
const NOISE_LEGEND_CONTROL_CLASS = 'noise-legend-control'
const DETAIL_PLAN_SOURCE_ID = 'detail-plans'
const DETAIL_PLAN_FILL_LAYER_ID = 'detail-plan-fill'
const DETAIL_PLAN_LINE_LAYER_ID = 'detail-plan-line'
const POI_SOURCE_ID = 'nearby-pois'
const POI_CIRCLE_LAYER_ID = 'nearby-pois-circle'
const POI_LABEL_LAYER_ID = 'nearby-pois-label'
const POI_SELECTED_SOURCE_ID = 'selected-poi'
const POI_SELECTED_LAYER_ID = 'selected-poi-highlight'
const NOISE_SOURCE_ID = 'noise-areas'
const NOISE_FILL_LAYER_ID = 'noise-areas-fill'
const NOISE_LINE_LAYER_ID = 'noise-areas-line'
const PARCEL_SELECTED_LAYER_ID = 'parcel-fill-selected'

const NOISE_AREA_COLOR = [
    'step',
    ['to-number', ['coalesce', ['get', 'MYRAKLASS'], ['get', 'db'], ['get', 'noise_db'], 45]],
    '#22c55e',
    50,
    '#84cc16',
    55,
    '#facc15',
    60,
    '#f97316',
    65,
    '#ef4444',
    70,
    '#7e22ce',
]
const NOISE_LEGEND_STEPS = [
    ['45-49 dB', '#22c55e'],
    ['50-54 dB', '#84cc16'],
    ['55-59 dB', '#facc15'],
    ['60-64 dB', '#f97316'],
    ['65-69 dB', '#ef4444'],
    ['70+ dB', '#7e22ce'],
]

let hoverPoiPopup = null
let pinnedPoiPopup = null

function addMapEvents(map, options) {
    map.on("mouseenter", "parcel-fill", () => {
        map.getCanvas().style.cursor = 'pointer'
    })

    map.on("mouseleave", "parcel-fill", () => {
        map.getCanvas().style.cursor = ''
    })

    map.on("click", "parcel-fill", (event) => {
        const poiFeatures = map.queryRenderedFeatures(event.point, {
            layers: [POI_CIRCLE_LAYER_ID, POI_LABEL_LAYER_ID, POI_SELECTED_LAYER_ID],
        })
        if (poiFeatures.length) {
            return
        }

        const feature = event.features?.[0]
        if (!feature) {
            console.error("Couldnt get features from parcel");
            return;
        }
        clearPinnedPoiPopup()
        setSelectedParcel(map, feature.properties.tunnus)
        if (options.onParcelClick) {
            options.onParcelClick(feature);
        }
    })
}

function setLayerVisibility(map, layerIds, visible) {
    const visibility = visible ? 'visible' : 'none'
    for (const layerId of layerIds) {
        if (map.getLayer(layerId)) {
            map.setLayoutProperty(layerId, 'visibility', visibility)
        }
    }
}

function movePoiLayersToTop(map) {
    for (const layerId of [POI_CIRCLE_LAYER_ID, POI_LABEL_LAYER_ID, POI_SELECTED_LAYER_ID]) {
        if (map.getLayer(layerId)) {
            map.moveLayer(layerId)
        }
    }
}

function setNoiseLegendVisible(visible) {
    document.querySelector(`.${NOISE_LEGEND_CONTROL_CLASS}`)?.classList.toggle('is-hidden', !visible)
}

function runWhenMapReady(map, callback) {
    if (map.loaded()) {
        callback()
        return
    }

    map.once('load', callback)
}

function emptyFeatureCollection() {
    return {
        type: 'FeatureCollection',
        features: [],
    }
}

function ensureNoiseAreaLayers(map) {
    if (map.getSource(NOISE_AREA_SOURCE_ID)) {
        movePoiLayersToTop(map)
        return
    }

    map.addSource(NOISE_AREA_SOURCE_ID, {
        type: 'geojson',
        data: `${API_BASE_URL}/api/noise-area/geojson`
    })

    map.addLayer({
        id: NOISE_AREA_SOURCE_FILL_ID,
        type: 'fill',
        source: NOISE_AREA_SOURCE_ID,
        layout: {
            visibility: 'none',
        },
        paint: {
            'fill-color': NOISE_AREA_COLOR,
            'fill-opacity': 0.22,
        }
    })

    map.addLayer({
        id: NOISE_AREA_SOURCE_LINE_ID,
        type: 'line',
        source: NOISE_AREA_SOURCE_ID,
        layout: {
            visibility: 'none',
        },
        paint: {
            'line-color': NOISE_AREA_COLOR,
            'line-width': 1,
            'line-opacity': 0.72,
        },
    })
    movePoiLayersToTop(map)
}

function ensureDetailPlanLayers(map) {
    if (map.getSource(DETAIL_PLAN_SOURCE_ID)) {
        movePoiLayersToTop(map)
        return
    }

    map.addSource(DETAIL_PLAN_SOURCE_ID, {
        type: 'geojson',
        data: `${API_BASE_URL}/api/detail-plans/geojson`
    })

    map.addLayer({
        id: DETAIL_PLAN_FILL_LAYER_ID,
        type: 'fill',
        source: DETAIL_PLAN_SOURCE_ID,
        layout: {
            visibility: 'none',
        },
        paint: {
            'fill-color': [
                'match',
                ['get', 'planseis_nimi'],
                'kehtiv',
                '#f97316',
                '#64748b',
            ],
            'fill-opacity': 0.22,
        }
    })

    map.addLayer({
        id: DETAIL_PLAN_LINE_LAYER_ID,
        type: 'line',
        source: DETAIL_PLAN_SOURCE_ID,
        layout: {
            visibility: 'none',
        },
        paint: {
            'line-color': [
                'match',
                ['get', 'planseis_nimi'],
                'kehtiv',
                '#ea580c',
                '#475569',
            ],
            'line-width': [
                'interpolate',
                ['linear'],
                ['zoom'],
                11,
                0.8,
                15,
                2.2,
            ],
        },
    })
    movePoiLayersToTop(map)

}

function createDetailPlanToggleControl(map) {
    return {
        onAdd() {
            const container = document.createElement('div')
            container.className = 'map-layer-control maplibregl-ctrl'
            container.setAttribute('debug', '')
            if (!SHOW_DEBUG_HTML) {
                container.classList.add('debug-hidden')
            }

            const label = document.createElement('label')
            label.className = 'map-layer-control__label'
            container.appendChild(label)

            const checkbox = document.createElement('input')
            checkbox.type = 'checkbox'
            label.appendChild(checkbox)

            const text = document.createElement('span')
            text.textContent = 'Detailplaneeringud'
            label.appendChild(text)

            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    ensureDetailPlanLayers(map)
                }

                setLayerVisibility(
                    map,
                    [
                        DETAIL_PLAN_FILL_LAYER_ID,
                        DETAIL_PLAN_LINE_LAYER_ID,
                    ],
                    checkbox.checked,
                )
                movePoiLayersToTop(map)
            })

            return container
        },
        onRemove() { },
    }
}

function createNoiseAreaToggleControl(map) {
    return {
        onAdd() {
            const container = document.createElement('div')
            container.className = 'map-layer-control maplibregl-ctrl'

            const label = document.createElement('label')
            label.className = 'map-layer-control__label'
            container.appendChild(label)

            const checkbox = document.createElement('input')
            checkbox.type = 'checkbox'
            label.appendChild(checkbox)

            const text = document.createElement('span')
            text.textContent = 'Müraala'
            label.appendChild(text)

            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    ensureNoiseAreaLayers(map)
                }

                setLayerVisibility(
                    map,
                    [
                        NOISE_AREA_SOURCE_FILL_ID,
                        NOISE_AREA_SOURCE_LINE_ID,
                    ],
                    checkbox.checked,
                )
                setNoiseLegendVisible(checkbox.checked)
                movePoiLayersToTop(map)
            })

            return container
        },
        onRemove() { },
    }
}

function ensurePoiLayers(map) {
    if (!map.getSource(POI_SOURCE_ID)) {
        map.addSource(POI_SOURCE_ID, {
            type: 'geojson',
            data: {
                type: 'FeatureCollection',
                features: [],
            },
        })
    }

    if (!map.getLayer(POI_CIRCLE_LAYER_ID)) {
        map.addLayer({
            id: POI_CIRCLE_LAYER_ID,
            type: 'circle',
            source: POI_SOURCE_ID,
            paint: {
                'circle-color': ['coalesce', ['get', 'color'], '#2563eb'],
                'circle-radius': [
                    'interpolate',
                    ['linear'],
                    ['zoom'],
                    11,
                    5,
                    15,
                    8,
                ],
                'circle-stroke-color': '#ffffff',
                'circle-stroke-width': 2,
                'circle-opacity': 0.92,
            },
        })
    }

    if (!map.getLayer(POI_LABEL_LAYER_ID)) {
        map.addLayer({
            id: POI_LABEL_LAYER_ID,
            type: 'symbol',
            source: POI_SOURCE_ID,
            minzoom: 14,
            layout: {
                'text-field': ['get', 'name'],
                'text-size': 11,
                'text-offset': [0, 1.25],
                'text-anchor': 'top',
                'text-max-width': 12,
                'text-optional': true,
            },
            paint: {
                'text-color': '#111827',
                'text-halo-color': '#ffffff',
                'text-halo-width': 1.5,
            },
        })
    }

    if (!map.getSource(POI_SELECTED_SOURCE_ID)) {
        map.addSource(POI_SELECTED_SOURCE_ID, {
            type: 'geojson',
            data: emptyFeatureCollection(),
        })
    }

    if (!map.getLayer(POI_SELECTED_LAYER_ID)) {
        map.addLayer({
            id: POI_SELECTED_LAYER_ID,
            type: 'circle',
            source: POI_SELECTED_SOURCE_ID,
            paint: {
                'circle-color': 'transparent',
                'circle-radius': [
                    'interpolate',
                    ['linear'],
                    ['zoom'],
                    11,
                    12,
                    15,
                    18,
                ],
                'circle-stroke-color': '#111827',
                'circle-stroke-opacity': 1,
                'circle-stroke-width': 3,
                'circle-opacity': 0.95,
            },
        })
    }
    movePoiLayersToTop(map)
}

function ensureNoiseLayers(map) {
    if (!map.getSource(NOISE_SOURCE_ID)) {
        map.addSource(NOISE_SOURCE_ID, {
            type: 'geojson',
            data: emptyFeatureCollection(),
        })
    }

    if (!map.getLayer(NOISE_FILL_LAYER_ID)) {
        map.addLayer(
            {
                id: NOISE_FILL_LAYER_ID,
                type: 'fill',
                source: NOISE_SOURCE_ID,
                paint: {
                    'fill-color': NOISE_AREA_COLOR,
                    'fill-opacity': 0.28,
                },
            },
            'parcel-line',
        )
    }

    if (!map.getLayer(NOISE_LINE_LAYER_ID)) {
        map.addLayer(
            {
                id: NOISE_LINE_LAYER_ID,
                type: 'line',
                source: NOISE_SOURCE_ID,
                paint: {
                    'line-color': NOISE_AREA_COLOR,
                    'line-width': 1.2,
                    'line-opacity': 0.82,
                },
            },
            'parcel-line',
        )
    }
}

function createNoiseLegendControl() {
    return {
        onAdd() {
            const container = document.createElement('div')
            container.className = `${NOISE_LEGEND_CONTROL_CLASS} maplibregl-ctrl is-hidden`

            const title = document.createElement('strong')
            title.textContent = 'Müra'
            container.appendChild(title)

            for (const [label, color] of NOISE_LEGEND_STEPS) {
                const row = document.createElement('span')
                row.className = 'noise-legend-row'

                const swatch = document.createElement('i')
                swatch.style.backgroundColor = color
                row.appendChild(swatch)

                const text = document.createElement('span')
                text.textContent = label
                row.appendChild(text)

                container.appendChild(row)
            }

            return container
        },
        onRemove() { },
    }
}

function clearPinnedPoiPopup() {
    pinnedPoiPopup?.remove()
    pinnedPoiPopup = null
}

function clearSelectedPoi(map) {
    const source = map.getSource(POI_SELECTED_SOURCE_ID)
    if (source) {
        source.setData(emptyFeatureCollection())
    }
}

function normalizeFeature(feature) {
    if (!feature?.geometry) {
        return null
    }

    return {
        type: 'Feature',
        geometry: feature.geometry,
        properties: { ...(feature.properties || {}) },
    }
}

function domainLabel(value) {
    if (!value) {
        return ''
    }

    const href = /^https?:\/\//i.test(value) ? value : `https://${value}`
    try {
        return new URL(href).hostname.replace(/^www\./i, '')
    } catch {
        return String(value).replace(/^https?:\/\//i, '').replace(/^www\./i, '').split('/')[0]
    }
}

function createPoiPopupBody(properties) {
    const popupBody = document.createElement('div')
    popupBody.className = 'poi-popup'

    const title = document.createElement('strong')
    title.textContent = properties?.name || 'Lähedal asuv objekt'
    popupBody.appendChild(title)

    const meta = [
        properties?.subgroup,
        properties?.distanceLabel,
    ].filter(Boolean).join(' · ')
    if (meta) {
        const metaElement = document.createElement('small')
        metaElement.textContent = meta
        popupBody.appendChild(metaElement)
    }

    if (properties?.address) {
        const addressElement = document.createElement('span')
        addressElement.textContent = properties.address
        popupBody.appendChild(addressElement)
    }

    if (properties?.website) {
        const link = document.createElement('a')
        link.href = /^https?:\/\//i.test(properties.website)
            ? properties.website
            : `https://${properties.website}`
        link.target = '_blank'
        link.rel = 'noreferrer'
        link.textContent = domainLabel(properties.website)
        popupBody.appendChild(link)
    }

    return popupBody
}

function showPoiPopup(map, feature, pinned = false) {
    const coordinates = feature?.geometry?.coordinates
    if (!Array.isArray(coordinates)) {
        return
    }

    const popup = new maplibregl.Popup({
        closeButton: pinned,
        closeOnClick: false,
        offset: 14,
        className: 'poi-map-popup',
    })
        .setLngLat(coordinates)
        .setDOMContent(createPoiPopupBody(feature.properties))
        .addTo(map)

    if (pinned) {
        clearPinnedPoiPopup()
        pinnedPoiPopup = popup
        popup.on('close', () => {
            if (pinnedPoiPopup === popup) {
                pinnedPoiPopup = null
                clearSelectedPoi(map)
            }
        })
    } else {
        hoverPoiPopup?.remove()
        hoverPoiPopup = popup
    }
}

function addPoiEvents(map) {
    map.on('mouseenter', POI_CIRCLE_LAYER_ID, () => {
        map.getCanvas().style.cursor = 'pointer'
    })

    map.on('mousemove', POI_CIRCLE_LAYER_ID, (event) => {
        const feature = event.features?.[0]

        if (!feature) {
            return
        }

        showPoiPopup(map, feature, false)
    })

    function handlePoiClick(event) {
        const feature = event.features?.[0]
        if (!feature) {
            return
        }

        if (typeof event.preventDefault === 'function') {
            event.preventDefault()
        }
        event.originalEvent?.stopPropagation()
        focusPoiOnMap(map, feature)
    }

    map.on('click', POI_CIRCLE_LAYER_ID, handlePoiClick)
    map.on('click', POI_LABEL_LAYER_ID, handlePoiClick)

    map.on('mouseleave', POI_CIRCLE_LAYER_ID, () => {
        map.getCanvas().style.cursor = ''
        hoverPoiPopup?.remove()
        hoverPoiPopup = null
    })
}

function addParcelLayers(map) {
    map.addSource("tallinn_parcels", {
        type: "vector",
        tiles: [
            `${API_BASE_URL}/tallinn_parcels/{z}/{x}/{y}.pbf`
        ],
        minzoom: 10,
        maxzoom: 18,
    })

    map.addLayer({
        id: 'parcel-line',
        type: 'line',
        source: 'tallinn_parcels',
        'source-layer': 'tallinn_parcels',
        paint: {
            'line-color': '#166534',
            'line-width': 1.5,
        },
    })

    map.addLayer({
        id: 'parcel-fill',
        type: 'fill',
        source: 'tallinn_parcels',
        'source-layer': 'tallinn_parcels',
        paint: {
            'fill-color': '#22c55e3f',
            'fill-opacity': 0.35,
        },
    })

    map.addLayer({
        id: PARCEL_SELECTED_LAYER_ID,
        type: 'fill',
        source: 'tallinn_parcels',
        'source-layer': 'tallinn_parcels',
        paint: {
            'fill-color': '#f59e0b',
            'fill-opacity': 0.34,
        },
        filter: ['==', ['get', 'tunnus'], '']
    })

    map.addLayer({
        id: 'parcel-selected-line',
        type: 'line',
        source: 'tallinn_parcels',
        'source-layer': 'tallinn_parcels',
        paint: {
            'line-color': '#92400e',
            'line-width': [
                'interpolate',
                ['linear'],
                ['zoom'],
                11,
                2.2,
                15,
                4,
            ],
        },
        filter: ['==', ['get', 'tunnus'], '']
    })
}

function flattenCoordinates(coordinates, result = []) {
    if (!Array.isArray(coordinates)) {
        return result
    }

    if (typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
        result.push(coordinates)
        return result
    }

    for (const child of coordinates) {
        flattenCoordinates(child, result)
    }

    return result
}

function boundsForFeature(feature) {
    const points = flattenCoordinates(feature?.geometry?.coordinates)
    if (!points.length) {
        return null
    }

    const bounds = new maplibregl.LngLatBounds(points[0], points[0])
    for (const point of points.slice(1)) {
        bounds.extend(point)
    }
    return bounds
}

function parcelFeaturesByTunnus(map, tunnus) {
    if (!tunnus || !map.loaded() || !map.getLayer('parcel-fill')) {
        return []
    }

    const rendered = map.queryRenderedFeatures(undefined, {
        layers: ['parcel-fill'],
        filter: ['==', ['get', 'tunnus'], tunnus],
    })
    if (rendered.length) {
        return rendered
    }

    try {
        return map.querySourceFeatures('tallinn_parcels', {
            sourceLayer: 'tallinn_parcels',
            filter: ['==', ['get', 'tunnus'], tunnus],
        })
    } catch {
        return []
    }
}

function parcelFeaturesByAddress(map, address) {
    if (!address || !map.loaded() || !map.getLayer('parcel-fill')) {
        return []
    }

    const rendered = map.queryRenderedFeatures(undefined, {
        layers: ['parcel-fill'],
        filter: ['==', ['get', 'l_aadress'], address],
    })
    if (rendered.length) {
        return rendered
    }

    try {
        return map.querySourceFeatures('tallinn_parcels', {
            sourceLayer: 'tallinn_parcels',
            filter: ['==', ['get', 'l_aadress'], address],
        })
    } catch {
        return []
    }
}

function focusParcelFeature(map, feature) {
    const tunnus = feature?.properties?.tunnus
    if (tunnus) {
        setSelectedParcel(map, tunnus)
    }

    const bounds = boundsForFeature(feature)
    if (bounds) {
        map.fitBounds(bounds, {
            padding: 96,
            maxZoom: 17,
            duration: 500,
        })
        return true
    }

    return false
}

export function createMap(id, options = {}) {
    const map = new maplibregl.Map({
        container: id,
        style: 'https://tiles.openfreemap.org/styles/bright',
        center: KERESE_CENTER,
        zoom: 12,
        minZoom: 11,
        maxBounds: [
            [21.5, 57.4],
            [28.3, 60.1],
        ],
    })

    map.on("load", () => {
        addParcelLayers(map)
        addMapEvents(map, options)
        ensurePoiLayers(map)
        addPoiEvents(map)
        ensureNoiseLayers(map)
        ensureDetailPlanLayers(map)
        ensureNoiseAreaLayers(map)
        movePoiLayersToTop(map)
        map.addControl(createDetailPlanToggleControl(map), 'top-left')
        map.addControl(createNoiseAreaToggleControl(map), 'top-left')
        map.addControl(createNoiseLegendControl(), 'bottom-left')
    })

    return map
}

export function setSelectedParcel(map, tunnus) {
    runWhenMapReady(map, () => {
        const filter = ['==', ['get', 'tunnus'], tunnus || '']
        if (map.getLayer(PARCEL_SELECTED_LAYER_ID)) {
            map.setFilter(PARCEL_SELECTED_LAYER_ID, filter)
        }
        if (map.getLayer('parcel-selected-line')) {
            map.setFilter('parcel-selected-line', filter)
        }
    })
}

export function focusParcelByTunnus(map, tunnus, fallbackAddress = '') {
    runWhenMapReady(map, () => {
        setSelectedParcel(map, tunnus)
        let attempts = 0

        function tryFocus() {
            attempts += 1
            const feature = parcelFeaturesByTunnus(map, tunnus)[0]
                || parcelFeaturesByAddress(map, fallbackAddress)[0]
            if (focusParcelFeature(map, feature) || attempts >= 4) {
                return
            }
            map.once('idle', tryFocus)
        }

        tryFocus()
    })
}

export function focusParcelByAddress(map, address) {
    runWhenMapReady(map, () => {
        const feature = parcelFeaturesByAddress(map, address)[0]
        focusParcelFeature(map, feature)
    })
}

export function setPoiOverlay(map, featureCollection) {
    runWhenMapReady(map, () => {
        ensurePoiLayers(map)
        const source = map.getSource(POI_SOURCE_ID)
        if (source) {
            source.setData(featureCollection)
        }
        movePoiLayersToTop(map)
    })
}

export function clearPoiOverlay(map) {
    setPoiOverlay(map, {
        type: 'FeatureCollection',
        features: [],
    })
    runWhenMapReady(map, () => {
        ensurePoiLayers(map)
        clearSelectedPoi(map)
    })
    hoverPoiPopup?.remove()
    hoverPoiPopup = null
    clearPinnedPoiPopup()
}

export function focusPoiOnMap(map, feature) {
    runWhenMapReady(map, () => {
        ensurePoiLayers(map)
        const selectedFeature = normalizeFeature(feature)
        if (!selectedFeature) {
            return
        }

        const source = map.getSource(POI_SELECTED_SOURCE_ID)
        if (source) {
            source.setData({
                type: 'FeatureCollection',
                features: [selectedFeature],
            })
        }
        movePoiLayersToTop(map)

        const coordinates = selectedFeature.geometry.coordinates
        if (Array.isArray(coordinates)) {
            map.easeTo({
                center: coordinates,
                zoom: Math.max(map.getZoom(), 15),
                duration: 450,
            })
        }
        showPoiPopup(map, selectedFeature, true)
    })
}

export function setNoiseOverlay(map, featureCollection) {
    runWhenMapReady(map, () => {
        ensureNoiseLayers(map)
        const source = map.getSource(NOISE_SOURCE_ID)
        if (source) {
            source.setData(featureCollection)
        }
        movePoiLayersToTop(map)
    })
}

export function clearNoiseOverlay(map) {
    setNoiseOverlay(map, emptyFeatureCollection())
}

export function getAddressSuggestions(map, query, limit = 6) {
    if (!query || !map.loaded()) {
        return []
    }

    const normalizedQuery = query.toLocaleLowerCase('et-EE')
    const queryTokens = normalizedQuery.split(/\s+/).filter(Boolean)
    const seen = new Set()
    let features = []

    try {
        features = features.concat(map.querySourceFeatures('tallinn_parcels', {
            sourceLayer: 'tallinn_parcels',
        }))
    } catch {
        // Ignore missing source while the map is still warming up.
    }

    try {
        features = features.concat(map.queryRenderedFeatures(undefined, { layers: ['parcel-fill'] }))
    } catch {
        // Ignore missing rendered layer while the map is still warming up.
    }

    return features
        .map((feature) => feature.properties?.l_aadress)
        .filter((address) => {
            if (!address || seen.has(address)) {
                return false
            }
            seen.add(address)
            const normalizedAddress = address.toLocaleLowerCase('et-EE')
            return queryTokens.every((token) => normalizedAddress.includes(token))
        })
        .map((address) => {
            const normalizedAddress = address.toLocaleLowerCase('et-EE')
            const starts = normalizedAddress.startsWith(normalizedQuery) ? 0 : 1
            const firstIndex = Math.min(
                ...queryTokens.map((token) => normalizedAddress.indexOf(token)).filter((index) => index >= 0),
            )
            return {
                address,
                score: starts * 1000 + firstIndex * 10 + address.length,
            }
        })
        .sort((a, b) => a.score - b.score || a.address.localeCompare(b.address, 'et-EE'))
        .map((item) => item.address)
        .slice(0, limit)
}

export function addGeoJsonLayerToMap(result_geojson, map) {
    setPoiOverlay(map, result_geojson)
}
