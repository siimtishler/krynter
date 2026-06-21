import './styles.css'
import { searchForParcel } from "./api/parcels.js"
import { getRequiredElement } from "./utils/utils.js"
import { createMap, addGeoJsonLayerToMap } from "./map/map.js"

const searchButton = getRequiredElement('search-button', HTMLButtonElement)
const searchInput = getRequiredElement('search-input', HTMLInputElement)
const map = createMap("map", {
    onParcelClick: async function(feature) {
        const response = await searchForParcel(feature.properties.tunnus)
    }
})


searchButton.addEventListener('click', () => {
    searchForParcel(searchInput.value);
})
