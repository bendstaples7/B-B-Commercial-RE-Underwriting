/**
 * Local ESLint rules for this project.
 *
 * Loaded via the 'local-rules' plugin in .eslintrc.cjs.
 * No npm package needed — just a local directory.
 */

'use strict'

/**
 * Rule: no-mirror-query-state
 *
 * Prevents this anti-pattern:
 *
 *   const [isLoading, setIsLoading] = useState(false)
 *   useEffect(() => {
 *     if (!mutation.isPending) setIsLoading(false)  // ← flagged
 *   }, [mutation.isPending])
 *
 * In TanStack Query v5, isPending transitions asynchronously on the next
 * render after mutate() is called. A useEffect that resets local state when
 * isPending is false will fire in the same render where isPending is still
 * false, immediately undoing any setIsLoading(true) called in the handler.
 *
 * The fix: drive button disabled/loading state directly from
 * mutation.isPending or query.isLoading — never mirror it into useState.
 */
const noMirrorQueryState = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Disallow mirroring TanStack Query isPending/isLoading into useState via useEffect. ' +
        'Drive loading state directly from mutation.isPending or query.isLoading instead.',
      recommended: true,
    },
    messages: {
      noMirrorInEffect:
        'Do not mirror "{{prop}}" into useState via useEffect. ' +
        'Read "{{prop}}" directly from the mutation/query object instead. ' +
        'See frontend-patterns steering doc for the correct pattern.',
    },
    schema: [],
  },

  create(context) {
    // Track useState setter names declared in the current function scope.
    // e.g. const [isLoading, setIsLoading] = useState(false)
    //       → setterNames = { 'setIsLoading' }
    const setterNames = new Set()

    // Known TanStack Query state properties that must not be mirrored.
    const QUERY_STATE_PROPS = new Set([
      'isPending',
      'isLoading',
      'isFetching',
      'isError',
      'isSuccess',
    ])

    return {
      // Collect useState destructuring: const [value, setter] = useState(...)
      VariableDeclarator(node) {
        if (
          node.id &&
          node.id.type === 'ArrayPattern' &&
          node.id.elements.length >= 2 &&
          node.init &&
          node.init.type === 'CallExpression' &&
          node.init.callee.name === 'useState'
        ) {
          const setter = node.id.elements[1]
          if (setter && setter.type === 'Identifier') {
            setterNames.add(setter.name)
          }
        }
      },

      // Detect useEffect bodies that call a useState setter with a TanStack
      // Query state property as the condition.
      //
      // Matches patterns like:
      //   useEffect(() => { if (!mutation.isPending) setIsLoading(false) }, [...])
      //   useEffect(() => { if (query.isLoading) setFetching(true) }, [...])
      CallExpression(node) {
        if (
          node.callee.type !== 'Identifier' ||
          node.callee.name !== 'useEffect'
        ) {
          return
        }

        const callback = node.arguments[0]
        if (!callback) return

        // Walk the callback body looking for calls to useState setters
        // that are guarded by a TanStack Query state property.
        walkNode(callback, (child) => {
          if (
            child.type === 'CallExpression' &&
            child.callee.type === 'Identifier' &&
            setterNames.has(child.callee.name)
          ) {
            // Check if any ancestor within this useEffect is an IfStatement
            // or ConditionalExpression whose test references a query state prop.
            const ancestors = context.getAncestors
              ? context.getAncestors()
              : []

            for (const ancestor of ancestors) {
              const test =
                ancestor.type === 'IfStatement'
                  ? ancestor.test
                  : ancestor.type === 'ConditionalExpression'
                  ? ancestor.test
                  : null

              if (test && referencesQueryStateProp(test)) {
                const prop = extractQueryStateProp(test)
                context.report({
                  node: child,
                  messageId: 'noMirrorInEffect',
                  data: { prop: prop || 'isPending/isLoading' },
                })
                return
              }
            }

            // Also flag direct dependency array references:
            // useEffect(() => { setIsLoading(mutation.isPending) }, [mutation.isPending])
            const args = child.arguments
            for (const arg of args) {
              if (referencesQueryStateProp(arg)) {
                const prop = extractQueryStateProp(arg)
                context.report({
                  node: child,
                  messageId: 'noMirrorInEffect',
                  data: { prop: prop || 'isPending/isLoading' },
                })
                return
              }
            }
          }
        })
      },
    }

    function referencesQueryStateProp(node) {
      if (!node) return false
      // mutation.isPending, query.isLoading, etc.
      if (
        node.type === 'MemberExpression' &&
        node.property.type === 'Identifier' &&
        QUERY_STATE_PROPS.has(node.property.name)
      ) {
        return true
      }
      // !mutation.isPending
      if (
        node.type === 'UnaryExpression' &&
        node.operator === '!' &&
        referencesQueryStateProp(node.argument)
      ) {
        return true
      }
      return false
    }

    function extractQueryStateProp(node) {
      if (node.type === 'MemberExpression') return node.property.name
      if (node.type === 'UnaryExpression') return extractQueryStateProp(node.argument)
      return null
    }

    function walkNode(node, visitor) {
      if (!node || typeof node !== 'object') return
      visitor(node)
      for (const key of Object.keys(node)) {
        if (key === 'parent') continue
        const child = node[key]
        if (Array.isArray(child)) {
          child.forEach((c) => walkNode(c, visitor))
        } else if (child && typeof child === 'object' && child.type) {
          walkNode(child, visitor)
        }
      }
    }
  },
}

module.exports = {
  rules: {
    'no-mirror-query-state': noMirrorQueryState,
  },
}
