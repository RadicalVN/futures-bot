export const api = {
    getAccounts: () => fetch('/api/accounts').then(r => r.json()),
    createAccount: (data) => fetch('/api/accounts', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }),
    
    getBots: () => fetch('/api/bots').then(r => r.json()),
    createBot: (data) => fetch('/api/bots', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }),
    updateBotStatus: (id, status) => fetch(`/api/bots/${id}/status`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status}) }),
    deleteBot: (id) => fetch(`/api/bots/${id}`, { method: 'DELETE' }),
    
    getEvents: (limit=50) => fetch(`/api/events?limit=${limit}`).then(r => r.json()),
    getTrades: (limit=50) => fetch(`/api/trades?limit=${limit}`).then(r => r.json()),
    
    getSymbols: () => fetch('/api/symbols').then(r => r.json()),
    getChartData: (symbol) => fetch(`/api/chart-data/${symbol.replace("/", "-")}`).then(r => r.json())
};
