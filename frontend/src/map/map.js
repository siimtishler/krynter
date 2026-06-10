import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './styles.css'

import { API_BASE_URL } from '../api/client.js'

const TALLINN_COORDINATES_GEO_JSON = [24.7536, 59.437]

export function createMap(id) {
    const map = new maplibregl.Map({
        container: id,
        style: 'https://tiles.openfreemap.org/styles/bright',
        center: [24.7020503, 59.3770407],
        zoom: 15,
        maxBounds: [
            [21.5, 57.4],
            [28.3, 60.1],
        ],
    })

    map.on("load", () => {
        map.addSource("kerese", {
            type: "vector",
            tiles: [
                `${API_BASE_URL}/vector_tiles/{z}/{x}/{y}.pbf`
            ],
            minzoom: 3,
            maxzoom: 5,
            bounds: [24.7020503, 59.3770407, 24.7175878, 59.3819951],
        })

        map.addLayer({
            id: 'kerese-fill',
            type: 'fill',
            source: 'kerese',
            'source-layer': 'kerese_tnv',
            paint: {
                'fill-color': '#22c55e',
                'fill-opacity': 0.35,
            },
        })

        map.addLayer({
            id: 'kerese-line',
            type: 'line',
            source: 'kerese',
            'source-layer': 'kerese_tnv',
            paint: {
                'line-color': '#166534',
                'line-width': 2,
            },
        })

    })

}

export function addGeoJsonLayerToMap(result_geojson, map) {

}
