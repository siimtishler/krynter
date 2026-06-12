import { apiGet } from "./client.js"
import { classifyParcelSearchInput } from "../utils/utils.js"

async function searchUsingAddress(address) {
    const query = new URLSearchParams({ address: address })
	return apiGet(`/api/search_address?${query}`)
}

export async function searchUsingCadastreCode(cadastreCode) {
    const query = new URLSearchParams({ cadastre_code: cadastreCode })
	return apiGet(`/api/search_cadastre?${query}`)
}

export async function getSearchForPlotResultJson(searchValue) {
	const searchInput = classifyParcelSearchInput(searchValue)

	if (searchInput.type === 'cadastre_code') {
		return searchUsingCadastreCode(searchInput.value)
	}

	return searchUsingAddress(searchInput.value)
}
