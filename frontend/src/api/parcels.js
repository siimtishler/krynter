import { apiGet } from "./client.js"
import { classifyParcelSearchInput } from "../utils/utils.js"


export async function searchForParcel(searchInput) {
	const searchInputClassified = classifyParcelSearchInput(searchInput)
	const query = new URLSearchParams({ searchable: searchInputClassified.value })
	const queryType = new URLSearchParams({ type: searchInputClassified.type })

	return apiGet(`/api/search?${queryType}&${query}`)
}

export async function analyzeDetailPlan(searchInput, options = {}) {
	const searchInputClassified = classifyParcelSearchInput(searchInput)
	const query = new URLSearchParams({
		searchable: searchInputClassified.value,
		type: searchInputClassified.type,
	})

	if (typeof options.enableLlmResolver === 'boolean') {
		query.set('enable_llm_resolver', String(options.enableLlmResolver))
	}

	if (typeof options.forceRefresh === 'boolean') {
		query.set('force_refresh', String(options.forceRefresh))
	}

	return apiGet(`/api/detail-plan-analysis?${query}`)
}
