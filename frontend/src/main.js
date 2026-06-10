import './styles.css'
import { apiGet } from "./api/client.js"
import { getRequiredElement } from "./utils/utils.js"
import { createMap, addGeoJsonLayerToMap } from "./map/map.js"

const searchButton = getRequiredElement('search-button', HTMLButtonElement)
const searchInput = getRequiredElement('search-input', HTMLInputElement)
const map = createMap("map")

async function searchForPlot() {
    console.log('tere')
    const query = new URLSearchParams({ address: searchInput.value })
    const result = await apiGet(`/api/search?${query}`)
    addGeoJsonLayerToMap(result, map)
    console.log(result)
}

async function loadVectorData() {
    const result = await apiGet("/vector_tiles/5/18/9.pbf")

    console.log(result)
}

loadVectorData()

searchButton.addEventListener('click', searchForPlot)