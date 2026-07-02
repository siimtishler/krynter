export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"

export async function apiGet(path) {
	const response = await fetch(`${API_BASE_URL}${path}`)

	if (!response.ok) {
		throw new Error(`API request failed: ${response.status}`)
	}
	const resp = await response.json()
	console.debug(resp)

	return resp
}

export async function apiPut(path, body) {
	const response = await fetch(`${API_BASE_URL}${path}`, {
		method: 'PUT',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(body),
	})

	if (!response.ok) {
		throw new Error(`API request failed: ${response.status}`)
	}
	const resp = await response.json()
	console.debug(resp)

	return resp
}

export async function apiDownload(path) {
	const response = await fetch(`${API_BASE_URL}${path}`)

	if (!response.ok) {
		throw new Error(`API request failed: ${response.status}`)
	}

	const disposition = response.headers.get('Content-Disposition') || ''
	const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i)
	const plainMatch = disposition.match(/filename="?([^";]+)"?/i)
	let filename = 'download.pdf'
	if (encodedMatch?.[1]) {
		filename = decodeURIComponent(encodedMatch[1])
	} else if (plainMatch?.[1]) {
		filename = plainMatch[1]
	}
	return {
		blob: await response.blob(),
		filename,
	}
}
