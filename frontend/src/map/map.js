import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './styles.css'

import { API_BASE_URL } from '../api/client.js'

const KERESE_CENTER = [24.709819, 59.3795179]
const DETAIL_PLAN_SOURCE_ID = 'detail-plans'
const DETAIL_PLAN_FILL_LAYER_ID = 'detail-plan-fill'
const DETAIL_PLAN_LINE_LAYER_ID = 'detail-plan-line'
const POI_SOURCE_ID = 'nearby-pois'
const POI_CIRCLE_LAYER_ID = 'nearby-pois-circle'
const POI_LABEL_LAYER_ID = 'nearby-pois-label'

let poiPopup = null

function addMapEvents(map, options) {
    let hoveredTunnus = null

    function handleParcelHover(event) {
        const feature = event.features?.[0]

        if (!feature) {
            return
        }

        const tunnus = feature.properties.tunnus

        if (tunnus === hoveredTunnus) {
            return
        }

        hoveredTunnus = tunnus
        map.getCanvas().style.cursor = 'pointer'
        map.setFilter('parcel-fill-hover', ['==', ['get', 'tunnus'], tunnus])
    }

    map.on("mousemove", "parcel-fill", handleParcelHover)

    map.on("mouseleave", "parcel-fill", () => {
        hoveredTunnus = null
        map.getCanvas().style.cursor = ''
        map.setFilter('parcel-fill-hover', ['==', ['get', 'tunnus'], ''])
    })

    map.on("click", "parcel-fill", (event) => {
        const feature = event.features?.[0]
        if (!feature) {
            console.error("Couldnt get features from parcel");
            return;
        }
        if (options.onParcelClick){
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

function runWhenMapReady(map, callback) {
    if (map.loaded()) {
        callback()
        return
    }

    map.once('load', callback)
}

function ensureDetailPlanLayers(map) {
    if (map.getSource(DETAIL_PLAN_SOURCE_ID)) {
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
            visibility: 'visible',
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
            visibility: 'visible',
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

}

function createDetailPlanToggleControl(map) {
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
            })

            return container
        },
        onRemove() {},
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
}

function addPoiEvents(map) {
    map.on('mouseenter', POI_CIRCLE_LAYER_ID, () => {
        map.getCanvas().style.cursor = 'pointer'
    })

    map.on('mousemove', POI_CIRCLE_LAYER_ID, (event) => {
        const feature = event.features?.[0]
        const coordinates = feature?.geometry?.coordinates

        if (!feature || !Array.isArray(coordinates)) {
            return
        }

        const name = feature.properties?.name || 'Lähedal asuv objekt'
        const address = feature.properties?.address
        const categoryLabel = feature.properties?.categoryLabel

        const popupBody = document.createElement('div')
        popupBody.className = 'poi-popup'

        const title = document.createElement('strong')
        title.textContent = name
        popupBody.appendChild(title)

        if (address) {
            const addressElement = document.createElement('span')
            addressElement.textContent = address
            popupBody.appendChild(addressElement)
        }

        if (categoryLabel) {
            const categoryElement = document.createElement('small')
            categoryElement.textContent = categoryLabel
            popupBody.appendChild(categoryElement)
        }

        if (!poiPopup) {
            poiPopup = new maplibregl.Popup({
                closeButton: false,
                closeOnClick: false,
                offset: 14,
                className: 'poi-map-popup',
            })
        }

        poiPopup
            .setLngLat(coordinates)
            .setDOMContent(popupBody)
            .addTo(map)
    })

    map.on('mouseleave', POI_CIRCLE_LAYER_ID, () => {
        map.getCanvas().style.cursor = ''
        poiPopup?.remove()
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
        id: 'parcel-fill-hover',
        type: 'fill',
        source: 'tallinn_parcels',
        'source-layer': 'tallinn_parcels',
        paint: {
            'fill-color': '#c522225e',
            'fill-opacity': 0.35,
        },
        filter: ['==', ['get', 'tunnus'], '']
    })
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
        map.addControl(createDetailPlanToggleControl(map), 'top-left')
    })

    return map
}

export function setPoiOverlay(map, featureCollection) {
    runWhenMapReady(map, () => {
        ensurePoiLayers(map)
        const source = map.getSource(POI_SOURCE_ID)
        if (source) {
            source.setData(featureCollection)
        }
    })
}

export function clearPoiOverlay(map) {
    setPoiOverlay(map, {
        type: 'FeatureCollection',
        features: [],
    })
    poiPopup?.remove()
}

export function addGeoJsonLayerToMap(result_geojson, map) {
    setPoiOverlay(map, result_geojson)
}
