export function getRequiredElement(id, type) {
    const element = document.getElementById(id)

    if (!(element instanceof type)) {
        throw new Error(`Missing or invalid element: #${id}`)
    }
    return element
}

export function classifyParcelSearchInput(value) {
    const trimmedValue = value.trim()
    const cadastreCodeRegex = /^\d{5}:\d{3}:\d{4}$/

    if (cadastreCodeRegex.test(trimmedValue)) {
        return {
            type: 'cadastre_code',
            value: trimmedValue,
        }
    }

    return {
        type: 'address',
        value: trimmedValue,
    }
}

export function throttle(callback, delayMs) {
    let lastRun = 0

    return function (...args) {
        const now = Date.now()

        if (now - lastRun < delayMs) {
            return
        }

        lastRun = now
        callback(...args)
    }
}