export default function Dots({ color }) {
  const style = color ? { color } : {};
  return (
    <span className="dots" style={style}>
      <span /><span /><span />
    </span>
  );
}
