import sys
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("WildlifeGuard MCP Server")

# Mock database of species
WILDLIFE_DATABASE = {
    "rhino": "Black Rhino (Critically Endangered). Sector: 3 and 4. Alert rangers immediately if spotted outside designated sanctuaries or near boundaries.",
    "elephant": "African Forest Elephant (Critically Endangered). Sector: All. Monitor migration corridors. Avoid disturbing herd paths.",
    "tiger": "Bengal Tiger (Endangered). Sector: 2. Solitary predator. Watch for territorial markings.",
    "gorilla": "Mountain Gorilla (Endangered). Sector: 1. Social group. Report any signs of respiratory illness or human contact.",
    "leopard": "Amur Leopard (Critically Endangered). Sector: 5. Extremely rare. Report sightings to conservation officers."
}

@mcp.tool()
def get_wildlife_db(species_name: str) -> str:
    """Retrieve details and conservation status of a species.
    
    Args:
        species_name: The name of the animal species (e.g., 'rhino', 'elephant').
    """
    name = species_name.lower().strip()
    return WILDLIFE_DATABASE.get(name, f"Species '{species_name}' is not in the endangered watch list database. Standard protocols apply.")

@mcp.tool()
def report_ranger_alert(alert_message: str, location: str, severity: str) -> str:
    """Simulate dispatching a high-priority ranger team to a location.
    
    Args:
        alert_message: The description of the threat (e.g., 'poachers with rifles').
        location: The coordinate or sector of the incident (e.g., 'Sector 4').
        severity: The severity level (e.g., 'HIGH', 'CRITICAL').
    """
    return f"ALERT DISPATCHED: Ranger Team alpha sent to {location}. Incident: '{alert_message}'. Severity: {severity}. Status: EN ROUTE."

@mcp.tool()
def get_weather_location(latitude: float, longitude: float) -> str:
    """Check weather, lighting, and camera battery status at specific coordinates.
    
    Args:
        latitude: The latitude coordinate.
        longitude: The longitude coordinate.
    """
    # Simple simulated logic based on coordinates
    is_night = (int(latitude + longitude) % 2 == 0)
    battery = int((latitude * 10 + longitude * 5) % 30) + 70  # 70% to 99%
    weather = "Rainy" if (latitude > 5.0) else "Clear"
    lighting = "Night/Dark (Requires IR camera)" if is_night else "Day/Bright"
    return f"Coordinates: ({latitude}, {longitude}) | Weather: {weather} | Lighting: {lighting} | Camera Battery: {battery}%"

if __name__ == "__main__":
    # FastMCP uses stdio transport by default when run as main
    mcp.run()
