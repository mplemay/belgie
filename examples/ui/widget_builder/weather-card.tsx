interface WeatherCardProps {
  city: string;
  condition: string;
  temperature: number;
}

export function WeatherCard({ city, condition, temperature }: WeatherCardProps) {
  return (
    <article className="weather-card">
      <p className="condition">{condition}</p>
      <h1>{city}</h1>
      <strong>{temperature}°C</strong>
    </article>
  );
}
