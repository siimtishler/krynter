export const API_BASE_URL = "http://127.0.0.1:8000"

export async function apiGet(path) {
	const response = await fetch(`${API_BASE_URL}${path}`)

	if (!response.ok) {
		throw new Error(`API request failed: ${response.status}`)
	}
	const resp = await response.json()
	console.debug(resp)

	return resp
}