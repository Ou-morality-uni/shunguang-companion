import { useId, useState, type Ref } from 'react';
import { Select } from 'radix-ui';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';

export type SelectOption = { value: string; label: string; group?: string; disabled?: boolean };

/** Glide-style highlight with Radix's keyboard, focus and popup positioning. */
export function GlideSelect({
  value,
  options,
  onValueChange,
  label,
  placeholder = '请选择',
  disabled,
  id,
  className = '',
  ref,
  required,
}: {
  value: string;
  options: SelectOption[];
  onValueChange: (value: string) => void;
  label: string;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
  ref?: Ref<HTMLButtonElement>;
  required?: boolean;
}) {
  const layoutId = useId();
  const systemReduced = useReducedMotion();
  const reduced = systemReduced || document.documentElement.dataset.reduceMotion === 'true';
  const [highlight, setHighlight] = useState(value);
  const groups = [...new Set(options.map((option) => option.group || ''))];
  return (
    <Select.Root
      value={value}
      onValueChange={(next) => {
        // Radix's hidden form control can emit an empty value while options load.
        if (next && options.some((option) => option.value === next && !option.disabled)) onValueChange(next);
      }}
      disabled={disabled}
      required={required}
      onOpenChange={(open) => {
        if (open) setHighlight(value);
      }}
    >
      <Select.Trigger ref={ref} id={id} className={`glide-trigger ${className}`} aria-label={label}>
        <Select.Value placeholder={placeholder}>
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={value}
              className="glide-value"
              initial={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : -2 }}
              transition={{ duration: reduced ? 0 : 0.12 }}
            >
              {options.find((option) => option.value === value)?.label || placeholder}
            </motion.span>
          </AnimatePresence>
        </Select.Value>
        <Select.Icon>
          <ChevronDown size={14} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="glide-menu" position="popper" sideOffset={6} collisionPadding={12}>
          <Select.ScrollUpButton className="glide-scroll">
            <ChevronUp size={14} />
          </Select.ScrollUpButton>
          <Select.Viewport>
            {groups.map((group) => (
              <Select.Group key={group}>
                {group && <Select.Label className="glide-group">{group}</Select.Label>}
                {options
                  .filter((option) => (option.group || '') === group)
                  .map((option) => (
                    <Select.Item
                      key={option.value}
                      value={option.value}
                      disabled={option.disabled}
                      className="glide-option"
                      onFocus={() => setHighlight(option.value)}
                      onPointerMove={() => !option.disabled && setHighlight(option.value)}
                    >
                      {highlight === option.value && (
                        <motion.span
                          className="glide-highlight"
                          layoutId={layoutId}
                          transition={reduced ? { duration: 0 } : { type: 'tween', duration: 0.22 }}
                        />
                      )}
                      <Select.ItemText>{option.label}</Select.ItemText>
                      <Select.ItemIndicator>
                        <Check size={14} />
                      </Select.ItemIndicator>
                    </Select.Item>
                  ))}
              </Select.Group>
            ))}
          </Select.Viewport>
          <Select.ScrollDownButton className="glide-scroll">
            <ChevronDown size={14} />
          </Select.ScrollDownButton>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
