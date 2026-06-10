export function getRequiredElement(id, type) {
    const element = document.getElementById(id)

    if (!(element instanceof type)) {
        throw new Error(`Missing or invalid element: #${id}`)
    }
    return element
}