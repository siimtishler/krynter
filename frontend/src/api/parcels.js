import { apiGet } from "./client.js"
import { classifyParcelSearchInput } from "../utils/utils.js"


export async function searchForParcel(searchInput) {
	const searchInputClassified = classifyParcelSearchInput(searchInput)
	const query = new URLSearchParams({ searchable: searchInputClassified.value })
	const queryType = new URLSearchParams({ type: searchInputClassified.type })

	return apiGet(`/api/search?${queryType}&${query}`)
}