export default function run(input: { name: string }): { greeting: string } {
  return { greeting: `Hello, ${input.name}!` };
}
